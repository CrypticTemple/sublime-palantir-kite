import sublime
import xml.sax
try:
	from cStringIO import *
except:
	from StringIO import *

def readlines(view):
	for region in view.lines(sublime.Region(0, view.size())):
		yield (region, view.substr(region))

class NamespaceHandler(xml.sax.ContentHandler):
	'''see if an XML file contains a certain set of namespaces'''
	def __init__(self, *check):
		self.look = set(check)
		self.seen = set()
		self.found = False

	def _add(self, name):
		(namespace, local) = name
		if namespace is None:
			return
		self.seen.add(namespace)
		if namespace in self.look:
			self.found = True

	def startElementNS(self, name, qname, attr):
		self._add(name)
		for aname, value in attr.items():
			self._add(aname)
		return

	def check(self, text):
		parser = xml.sax.make_parser()
		parser.setContentHandler(self)
		parser.setFeature(xml.sax.handler.feature_namespaces, 1)
		# parser.setFeature(xml.sax.handler.feature_namespace_prefixes, 1)
		try:
			stream = StringIO(text)
			parser.parse(stream)
		except Exception, e:
			print 'NamespaceHandler: error parsing -',e
			return False
		return self.found

class PositionHandler(xml.sax.ContentHandler):
	'''determine the most recent element in/around the current cursor position'''
	def __init__(self, view, name=None):
		self.locator = None
		self.view = view
		self.name = name
		self.elem = None
		self.attr = None
		self.done = False

	def setDocumentLocator(self, locator):
		self.locator = locator

	def startDocument(self):
		if self.locator is None:
			raise RuntimeError('The parser does not support locators')
		return

	def startElementNS(self, name, qname, attr):		
		if self.done:
			return
		(namespace, localname) = name
		if self.name is not None and self.name != localname:
			return
		
		self.elem = name
		self.attr = attr

		# assuming position is AFTER the end of the element, otherwise, this doesn't work
		line = self.locator.getLineNumber()
		col = self.locator.getColumnNumber()
		pt = self.view.text_point(line, col)
		if pt >= self.position:
			self.done = True

	def check(self):
		text = get_text(self.view)
		self.position = self.view.sel()[0].begin()
		print self.position
		parser = xml.sax.make_parser()
		parser.setContentHandler(self)
		parser.setFeature(xml.sax.handler.feature_namespaces, 1)
		# parser.setFeature(xml.sax.handler.feature_namespace_prefixes, 1)
		try:
			stream = StringIO(text)
			parser.parse(stream)
		except Exception, e:
			print 'PositionHandler: error parsing -',e
			return False
		return (self.elem, self.attr)

class FeedingPositionHandler(xml.sax.ContentHandler):
	'''determine the most recent element in/around the current cursor position by feeding it prior XML line by line'''
	def __init__(self, view, *names):
		self.view = view
		self.names = set(names)
		self.elem = None
		self.attr = None
		self.error = None
		self.done = False

	def startElementNS(self, name, qname, attr):		
		if self.done:
			return
		(namespace, localname) = name
		if len(self.names) > 0 and localname not in self.names:
			return
		# assuming position is AFTER the end of the element, otherwise, this doesn't work
		if self.region.begin() >= self.position:
			self.done = True
			return
		# print localname
		self.elem = name
		self.attr = attr
	
	def check(self):
		self.position = self.view.sel()[0].begin()
		parser = xml.sax.make_parser()
		parser.setContentHandler(self)
		parser.setFeature(xml.sax.handler.feature_namespaces, 1)
		# we only need to parse up to where the cursor is - the rest of the XML can be garbage
		try:
			for region, line in readlines(self.view):
				self.region = region
				parser.feed(line)
				if self.done:
					break
		except Exception, e:
			self.error = e
			print 'FeedingPositionHandler: error parsing -',e
		return (self.elem, self.attr, self.error)