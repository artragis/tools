"""
Copyright (c) 2015 "Vade Retro Technology"
anonemail is an email anonymization script

This file is part of anonemail.

anonemail is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

#!/usr/bin/python3
# coding = utf8
 
import email,smtplib,re, urllib, io
import argparse,sys,base64, quopri, random
from bs4 import BeautifulSoup
from email.parser import BytesFeedParser
from email.header import decode_header,Header

# Separators for getting user "parts" as in name.surname@email.tld or name_surname@email.tld
USERSEP = re.compile("[.\-_]")
# Separators for multiple/list of emails
# eg: in the To field
TKENSEP = re.compile("[ ,;]")
# List of emails used
FROMADDR="from@email.tld"
FWDADDR = "sampling@email.tld"
ERRADDR = "oops@email.tld"
SMPADDR = "sampling@email.tld"
# Server to forward anonymized messages to
SRVSMTP = "localhost"
# Custom headers to anonymize ( List Id…)
CSTMHDR = ( "X-Mailer-RecptId", )
# Headers to decode before tokenizing ( RFC 2822 )
CODDHDR = ( "To", "Cc", "Subject" ) 

addr_rgx = re.compile("for ([^;]+);") # to clean received headers
url_rgx = re.compile('http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+')

def replace(text, elmts):
	""" Find tokens in part and replace them """
	count = 0
	for elmt in elmts:
		ins_elmt = re.compile(re.escape(elmt), re.IGNORECASE)
		(text, c) = ins_elmt.subn( ano_x(elmt), text)
		count = count + c
	return (text, count)

def ano_x(str):
	""" Replace a string by 'xxxx' """
	return re.sub('\w', 'x', str)

	
def tokenize_to(to):
	""" Parse the To field and extract elements that should be anonymized """
	emails = set()
	tokens = set()
	
	# Get both aliases and email addresses
	temp  = TKENSEP.split(to.lower())
	for t in temp:
		t = clean_token(t)
		if '@' in t:
			emails.add(t)
		elif len(t) != 0:
			tokens.add(t)
			
	# For every email address, extract element of interest (name, surname, domain…)
	for e in emails:
		(fulluser, todom) = e.split('@')
		for i in USERSEP.split(fulluser, 4):
			if len(i) > 2: 
				tokens.add(i)
		tokens.add(todom)
		
	return tokens
	
def clean_token(t):
	""" Clean token from unwanted character """
	return t.strip('<>" \n\t')
	
def error(msg):
	""" Forward message to the error handling email address """
	s = smtplib.SMTP(SRVSMTP)
	s.send_message(msg,args.from_addr,args.err_addr)
	s.quit()
	exit(1)

def get_dest(msg, orig_to):
	""" Find the recipient(s) """
	dest = []
	
	# To
	if msg.get('to') is not None and '@' in msg.get('to'):
		dest.extend(msg.get_all('to'))

	# Cc
	if msg.get('cc') is not None and '@' in msg.get('cc'):
		dest.extend(msg.get_all('cc'))

	# If To or Cc, decode them
	if len(dest) != 0:
		dest = decode_hdr(dest)

	# If no To nor Cc, we look for recipient into the received
	if orig_to is None:
		for rcvd in msg.get_all('Received'):
			dest.extend(addr_rgx.findall(rcvd,re.IGNORECASE))
	else:
		dest.extend(orig_to)

	return dest

def decode_hdr(dest):
	""" Decode non-ASCII header fields """
	dcd_dest = []

	for i in dest:
		for (b, charset) in decode_header(i):
			# Dirty hack - if bytes
			if isinstance(b, bytes):
				dcd_str = b.decode(charset) if charset != None else b.decode()
				dcd_dest.append(clean_token(dcd_str))
			# or string (because Python returns both)
			else:
				dcd_dest.append(clean_token(b))
			
	return dcd_dest

def encode(part, charset = "utf-8" , cte = None):
	""" Reencode part using Content-Transfer-Encoding information """
	donothing = [ '7bit', '8bit' ]
	encoders = { "base64": base64.b64encode, \
			"quoted-printable": quopri.encodestring }
	if cte is None:
		return part
	if cte.lower() in donothing:
		return part
	elif cte in encoders:
		buffer = part.encode(charset, errors='replace')
		coded_str = encoders[cte](buffer)
		return coded_str.decode()
	else:
		return "!ERR!"
		
def url_replace(text):
	""" Replace tokens inside urls """
	
	urlz = url_rgx.finditer(text)
	for url in urlz:
		o = urllib.parse.urlparse(url.group(0))
		if o.query is not "":
			new_url = url_ano_params(o)
			text = text[:url.start()] + new_url + text[url.end():]
	
	return text
	
def url_ano_params(o):
	""" Replace every parameter in URLs """
	new_query = []
	for qs in urllib.parse.parse_qsl(o.query):
		new_query.append( ( qs[0], ano_x(qs[1]) ) )
		new_url = urllib.parse.urlunparse( (o[0], o[1], o[2], o[3], urllib.parse.urlencode(new_query), o[5]) )
		
	return new_url
	
def url_replace_html(html):
	""" Parse HMTL and extract URLs """
	
	soup = BeautifulSoup(html)
	for tag in soup.findAll('a', href=True):
		url = tag['href']
		o = urllib.parse.urlparse(url)
		if o.query is not "":
			new_url = url_ano_params(o)
			tag['href'] = new_url
		
	return str(soup)

def main():
	global args
	
	parser = argparse.ArgumentParser(description='')
	group = parser.add_mutually_exclusive_group()
	group.add_argument('-', help="Read from standard input", dest='stdin', action='store_true')
	group.add_argument('-i','--infile', help="Read from a file (eml/plain text format)", nargs='?')
	parser.add_argument('--from', dest='from_addr', help="Sender address", default=FROMADDR)
	parser.add_argument('--to', dest='to_addr', help="Recipient address", default=FWDADDR)
	parser.add_argument('--orig-to', dest='orig_to', help="To used in SMTP transaction", nargs='*', default=None)
	parser.add_argument('--err', dest='err_addr', help="Error handling address", default=ERRADDR)
	parser.add_argument('--sample', dest='smpl_addr', help="Sampling address", default=SMPADDR)
	parser.add_argument('--no-dkim', dest='no_dkim', help="Remove DKIM fields", action='store_true')
	
	args = parser.parse_args()

	# Read email
	p=email.parser.BytesFeedParser()
	if args.stdin or args.infile is None:
		input = io.BufferedReader(sys.stdin.buffer)
	else:
		input = open(args.infile, 'rb')
	p.feed(input.read())
	msg = p.close()
	input.close()
	
	# Check for invalid (0 bytes) message
	if len(msg) == 0:
		error(msg, args)
	
	# Grab recipient from To field
	dest = get_dest(msg, args.orig_to)
	if len(dest) == 0:
		error(msg)
	
	# Get tokens from recipient
	elmts = set()
	for d in dest:
		elmts.update(tokenize_to(d))
		
		elmts = sorted( elmts, key=str.__len__, reverse = True )
	
	# Main part - loop on every part of the email
	for part in msg.walk():
		if not part.is_multipart() and part.get_content_maintype() == 'text':
			charset = part.get_content_charset()
		
		        # If there is a charset, we decode the content
			if charset is None:
				payload = part.get_payload()
				new_load = replace(payload, elmts)[0]
			else:
				payload = part.get_payload(decode=True).decode(charset)
				new_load = replace(payload, elmts)[0]

			# URL anonymization
			if part.get_content_subtype() == 'plain':
				new_load = url_replace(new_load)
			elif part.get_content_subtype() == 'html':
				new_load = url_replace_html(new_load)
			
			# Encoding back in the previously used encoding (if any)
			cdc_load = encode(new_load, charset, part.get('content-transfer-encoding'))
			if cdc_load == "!ERR!":
				error(msg)
			else:
				part.set_payload(cdc_load)
	
	# Looking for custom header to clean
	for cstmhdr in CSTMHDR:
		if cstmhdr in msg.keys():
			msg.replace_header(cstmhdr, ano_x( msg.get(cstmhdr)) )
			
	# Anonmyzation of encoded headers
	for coddhdr in CODDHDR:
		if coddhdr in msg.keys():
			ano_hdr = []
			for ( b, charset) in decode_header(msg.get(coddhdr)):
				
				if charset != None:
					dcd_hdr = b.decode(charset)
					(dcd_hdr, count) = replace(dcd_hdr, elmts)
					ano_hdr.append( (dcd_hdr , charset) )
				elif isinstance(b,str):
					ano_hdr.append( (b, charset) )
				else:
					ano_hdr.append( (b.decode(), charset) )

			msg.replace_header( coddhdr, email.header.make_header(ano_hdr) )
			
	# If defined, clean DKIM fields
	if args.no_dkim:
		del msg["DKIM-Signature"]
		del msg["DomainKey-Signature"]
	
	# Concatenate the anonymized headers with anonymized body = BOUM ! anonymized email !
	hdr_end = msg.as_string().find('\n\n')
	if hdr_end == -1:
		error(msg)
	else:
		hdr = msg.as_string()[:hdr_end]
		new_hdr = url_replace(hdr)
		(new_hdr, count) = replace(new_hdr,elmts)
		final = new_hdr + msg.as_string()[hdr_end:]

		
	## Force reencoding to avoid issues during sending with Python SMTP Lib
	if msg.get_content_charset() is not None:
		final = final.encode(msg.get_content_charset(), errors='replace')
	else:
		for charset in msg.get_charsets():
			if charset is not None:
				final = final.encode(charset, errors='replace')
				break

	s = smtplib.SMTP(SRVSMTP)
	
	# Sampling part 
	if random.randint(0,10) == 0:
		s.sendmail(args.from_addr,args.smpl_addr,final)

	# Send final message 
	s.sendmail(args.from_addr,args.to_addr,final)

	s.quit()
	exit(0)


if __name__ == '__main__':
    main()
