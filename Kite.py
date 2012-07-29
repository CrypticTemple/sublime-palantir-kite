import sublime_plugin
import sublime
import sys
import os
import re
import xml.sax
import subprocess
import stat
import time
from handlers import *
from glob import glob
from collections import defaultdict
try:
    from cStringIO import *
except ImportError:
    from StringIO import *

# namespaces for XML
NAMESPACES = {
    'kite': 'http://www.palantirtech.com/pg/schema/kite/'
}

# default homes
HOMES = {
    'nt': 'C:\\Palantir',
    None: '/opt/palantir/dispatchServer'
}

SETTINGS_FILE = 'Kite.sublime-settings'

def get_text(view):
    return view.substr(sublime.Region(0, view.size()))

def uncapitalize(s):
    return s[0].lower() + s[1:]

def is_xml_syntax(view):
    return "XML.tmLanguage" in view.settings().get('syntax')

def is_kite_syntax(view):
    return "Kite.tmLanguage" in view.settings().get('syntax')

def most_recent(path, pattern='*.*', filt=None):
    '''get the most recent file in a directory'''
    if os.path.isfile(path):
        return path
    files = []
    for fn in glob(os.path.join(path,pattern)):
        t = time.localtime(os.stat(fn)[stat.ST_CTIME])
        files.append((t, fn))
    if filt is not None:
        files = filter(filt, files)
    if len(files) <= 0:
        return None
    files.sort()
    files.reverse()
    return files[0][1]

def find_home(setting):
    '''find palantir's home'''
    if setting is not None and os.path.isdir(setting):
        return setting
    elif os.name == 'nt' and os.path.isdir(HOMES['nt']):
        p = most_recent(HOMES['nt'], '[0-9].*', lambda (t,f): os.path.isdir(f))
        # settings.set('home',p)
        return p
    elif os.path.isdir(HOMES[None]):
        # settings.set('home',HOMES[None])
        return HOMES[None]
    return None

def find_workspace_cache():
    # find the home directory
    home = None
    if 'HOME' in os.environ:
        home = os.environ['HOME']
    elif 'USERPROFILE' in os.environ:
        home = os.environ['USERPROFILE']
    if not home or not os.path.isdir(home):
        return None
    # find the cache
    cache = os.path.join(home,'.palantir','cache')
    if not os.path.isdir(cache):
        return None
    # most recent workspace directory in cache 
    latest = most_recent(cache,'[0-9a-fA-F]*', lambda (t,f): os.path.isdir(f))
    bootstrap = os.path.join(latest, 'bootstrap')
    if os.path.exists(bootstrap):
        return bootstrap
    return None

def in_scope(view, location, scope):
    return sublime.score_selector(view.scope_name(location), scope) > 0

def in_param(view, location):
    return in_scope(view, location, 'meta.tag.block.param.xml')

def in_proc(view, location):
    return in_scope(view, location, 'meta.tag.block.rowprocessor.xml')

def in_prov(view, location):
    return in_scope(view, location, 'meta.tag.block.rowprovider.xml')

def in_global(view, location):
    return in_scope(view, location, 'meta.tag.block.global-params.xml')

def in_attr_string(view, location):
    return in_scope(view, location, 'string.quoted.double.xml')

def shorten(uri, prefix=''):
    '''make substitution easier to follow by shortening classes / uris'''
    if not '.' in uri:
        return uri
    spl = uri.split('.')
    i = 0
    top = len(spl) - 1
    ret = []
    for s in spl:
        if i >= top or (prefix and prefix in s):
            ret.append(s)
        else:
            ret.append(s[0])
        i += 1
    return '.'.join(ret)

class PalantirPluginException(Exception):
    pass

class Kite(object):
    '''storage bin for parameters and class names'''
    def __init__(self, home, jars, jdk=None):
        self.home = home
        self.jars = jars
        self.jdk = jdk
        self.processors = defaultdict(set)
        self.providers = defaultdict(set)
        kjar = self.find_kite_jar()
        if kjar and kjar not in self.jars:
            self.jars.append(kjar)
        self.reset()

    def reset(self):
        self.processors = defaultdict(set)
        self.providers = defaultdict(set)

    def load(self, settings):
        self.reset()
        k = settings.get('kite')
        if k is None:
            return
        for p in ['providers','processors']:
            d = self.__dict__[p]
            for key, value in k[p].items():
                if key == '':
                    key = None
                d[key] = set(value)

    def store(self, settings):
        convert = lambda p: dict([(k if k else "", list(v)) for k, v in p.iteritems()])
        settings.set('kite', {
            'providers': convert(self.providers),
            'processors': convert(self.processors)
        })

    def find_kite_jar(self):
        path = None
        if self.home and os.path.isdir(self.home):
            path = os.path.join(self.home,'lib','server')
        else:
            cache = find_workspace_cache()
            path = cache if cache else None
        if not path:
            return None
        return most_recent(path,'[Kk]ite*.jar')

    def extend(self, d, jar, klass):
        abstract, params = self.parse_javap(jar, klass)
        key = klass if not abstract else None
        d[key] = d[key].union(set(params))

    def get_global_params(self):
        return set().union(*self.processors.values())

    def parse(self):
        if not self.jars:
            return
        self.reset()
        for jar in self.jars:
            provs, procs = self.parse_jar(jar)
            for p in provs:
                self.extend(self.providers, jar, p)
            for p in procs:
                self.extend(self.processors, jar, p)
        return

    def parse_jar(self, jar):
        '''get a list of all the Kite classes in a jar file'''
        # hard way: build a tree of everything that implements RowProvider / Processor or extends one of the abstract classes
        # easy way: look for all classes that end in Provider / Processor
        return self.parse_jar_easy(jar)

    def parse_jar_easy(self, jar):
        '''easy way: look for all classes that end in Provider / Processor'''
        out, err = self.exec_jar(jar)
        if err:
            print err
            return (set(), set())

        providers = set()
        processors = set()

        f = StringIO(out)
        for line in f:
            line = line.strip()
            # ignore nested classes
            if not line.endswith('.class') or '$' in line:
                continue
            # swap slashes for periods, minus .class
            klass = line.replace('/','.')[0:len(line) - 6]
            if klass.endswith('Provider'):
                providers.add(klass)
            elif klass.endswith('Processor'):
                processors.add(klass)
            continue
        return (providers, processors)

    def parse_javap(self, jar, klass):
        '''gather all the setters in the class'''
        ret = set()
        abstract = False

        out, err = self.exec_javap(jar, klass)
        if err:
            print err
            return (abstract, ret)

        f = StringIO(out)
        first = True
        signature = 'public void set'
        first_type = '(java.lang.String'

        for line in f:
            line = line.strip()
            if line.startswith('Compiled from'):
                continue
            if first:
                first = False
                if 'abstract ' in line or 'interface ' in line:
                    abstract = True
                continue
            idx = line.find(signature)
            par = line.find(first_type, idx)
            if -1 in (idx, par):
                continue
            ret.add(uncapitalize(line[idx + len(signature):par]))
        return (abstract, ret)

    def _exec(self, executable, opts):
        sinfo = None
        shell = False
        # it's either this or finding it in the path
        if self.jdk is None:
            shell = True
        elif os.name == 'nt':
            executable = os.path.join(self.jdk,'bin\\' + executable + '.exe')
            sinfo = subprocess.STARTUPINFO()
            sinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            sinfo.wShowWindow = subprocess.SW_HIDE
        else:
            executable = os.path.join(self.jdk,'bin/' + executable)

        cmd = [ executable ] + opts
        if shell:
            cmd = ' '.join(cmd)
        print cmd
        popen = subprocess.Popen(cmd,
              stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
              shell=shell, startupinfo=sinfo)
        return popen.communicate()

    def exec_jar(self, jar):
        return self._exec('jar', ['tf', jar])

    def exec_javap(self, jar, klass):
        return self._exec('javap', ['-public','-classpath', jar, klass])

class Ontology(object):
    '''storage bin for ontology URIs'''
    def __init__(self, home, path):
        self.home = home
        self.path = path
        self.file = None
        self.reset()

    def reset(self):
        self.properties = set()
        self.objects = set()
        self.links = set()
        # self.components = {}

    def load(self, settings):
        self.reset()
        k = settings.get('ontology.uris')
        if k is None:
            return
        for p in ['properties','objects','links']:
            self.__dict__[p] = set(k[p])

    def store(self, settings):
        settings.set('ontology.uris', {
            'properties': list(self.properties),
            'objects': list(self.objects),
            'links': list(self.links)
        })

    def get_all(self):
        return self.properties.union(self.objects, self.links)

    def parse(self):
        '''use ontologyMerge.sh to create a listing of uris'''
        if None in (self.home, self.path):
            return
        self.file = most_recent(self.path, '*.ont')
        if self.file is None:
            return
        out, err = self.get_listing()
        if err:
            print err
            return

        f = StringIO(out)
        addto = None
        for line in f:
            if line.startswith('// '):
                if line.startswith('// [[PT OBJECT TYPES]]'):
                    addto = self.objects
                elif line.startswith('// [[PROPERTY TYPES]]'):
                    addto = self.properties
                elif line.startswith('// [[LINK TYPES]]'):
                    addto = self.links
                else:
                    addto = None
                continue
            elif addto is not None:
                val = line.replace('*','').strip()
                addto.add(val)

    def get_listing(self):
        executable = None
        sinfo = None
        if os.name == 'nt':
            executable = os.path.join(self.home,'bin\\dist_ontology_merge.bat')
            sinfo = subprocess.STARTUPINFO()
            sinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            sinfo.wShowWindow = subprocess.SW_HIDE
        else:
            executable = os.path.join(self.home,'bin/unix/ontologyMerge.sh')
        # do we need a temporary file here? or a named pipe of some kind?
        cmd = [ executable, '--file', self.file, '--list', '-' ]
        popen = subprocess.Popen(cmd,
              stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
              startupinfo=sinfo)
        return popen.communicate()

class PalantirKiteRefreshSettings(sublime_plugin.ApplicationCommand):
    def run(self):
        kite.reset()
        kite.parse()
        ontology.reset()
        ontology.parse()

class PalantirKiteSaveSettings(sublime_plugin.ApplicationCommand):
    def run(self):
        kite.store(settings)
        ontology.store(settings)
        sublime.save_settings(SETTINGS_FILE)
        
class PalantirKiteListener(sublime_plugin.EventListener):
    def check_kite(self, view):
        '''see if we're using the kite namespace as default'''
        handler = NamespaceHandler(NAMESPACES['kite'])
        return handler.check(get_text(view))

    def check_position(self, view):
        '''figure out where we are in the XML by parsing through it'''
        handler = FeedingPositionHandler(view)
        results = handler.check()
        # print 'last element:', results
        return results

    def check_param(self, view):
        '''figure out what kind of param we're writing to - processor, provider, or global'''
        handler = FeedingPositionHandler(view, 'rowprocessor', 'rowprovider', 'globalParams')
        results = handler.check()
        # print 'param element:', results
        return results

    def is_kite(self, view):
        '''are we editing a kite file?'''
        vset = view.settings()
        kite = vset.get('palantir.kite')
        if kite is not None:
            return kite
        if is_kite_syntax(view):
            vset.set('palantir.kite', True)
            return True
        elif not is_xml_syntax(view):
            # print 'not xml'
            # vset.set('palantir.kite', False)
            return False
        elif not self.check_kite(view):
            # print 'not kite'
            vset.set('palantir.kite', False)
            return False
        # print 'its kite'
        vset.set('syntax','Packages/Palantir/Kite.tmLanguage')
        vset.set('palantir.kite', True)
        return True

    def get_options(self, view, loc):
        '''figure out what we should return based off of where we are in the file'''
        # in a provider and in an attribute => provider classes
        if in_prov(view, loc) and in_attr_string(view, loc):
            print 'in provider class'
            return [k for k in kite.providers.keys() if k is not None]

        # in a processor and in an attribute => processor classes
        if in_proc(view, loc) and in_attr_string(view, loc):
            print 'in processor class'
            return [k for k in kite.processors.keys() if k is not None]

        # otherwise, if we're not in a parameter
        if not in_param(view, loc):
            print 'nothing to do'
            return []

        print 'in param'

        # inside a parameter attribute
        if in_attr_string(view, loc):
            print 'in attribute'
            # inside a provider
            if in_prov(view, loc):
                print 'in provider'
                elem, attr, error = self.check_param(view)
                klass = attr.get((None,'class'))
                return kite.providers[klass]
            # global params
            elif in_global(view, loc):
                print 'in global'
                return kite.get_global_params()
            # processor (global + processor class)
            print 'in processor'
            opts = []
            opts.extend(kite.processors[None])
            if in_proc(view, loc):
                elem, attr, error = self.check_param(view)
                klass = attr.get((None,'class'))
                opts.extend(kite.processors[klass])
            return opts

        # otherwise, our other options are appropriate URIs
        print 'in element content'
        elem, attr, error = self.check_position(view)
        key = attr.get((None,'key'))

        # TODO: More key content checks
        if key in ('linkType'):
            return ontology.links
        elif key in ('propertyType'):
            return ontology.properties
        elif key in ('objectType'):
            return ontology.objects
        elif 'Column' in key:
            # don't return URIs for column parameters
            return []
        # otherwise, return everything
        self.flags = 0
        return ontology.get_all()

    def on_query_completions(self, view, prefix, locations):
        # I'm not dealing with multiple cursors
        if not self.is_kite(view) or len(locations) <= 0:
            return []

        # reset completion behavior
        self.reset_flags()

        # kinds of completions:
        # * row provider / processor class
        # * row provider / processor params
        # * ontology uris / component uris

        loc = locations[0]
        opts = self.get_options(view, loc)

        # get the content of the entire scope
        reg = view.extract_scope(loc)
        prefix_reg = sublime.Region(reg.begin(), min(reg.end(), loc))
        if prefix:
            txt = view.substr(prefix_reg)
        else:
            txt = ''

        ret = [(shorten(k, prefix), k) for k in opts if k.startswith(txt)]
        ret.sort()
        if not ret:
            # print 'no options returned'
            return []

        # select the entire scope if we're doing a substitution
        sel = view.sel()
        sel.clear()
        sel.add(reg)

        return (ret, self.flags)

    def reset_flags(self):
        self.flags = sublime.INHIBIT_WORD_COMPLETIONS | sublime.INHIBIT_EXPLICIT_COMPLETIONS

    def on_load(self, view):
        if self.is_kite(view):
            self.check_position(view)
        return False

    def on_post_save(self, view):
        if self.is_kite(view):
            self.check_position(view)
        return False

settings = sublime.load_settings(SETTINGS_FILE)
home = settings.get('home', find_home(None))
kite = Kite(home, settings.get('jars'), settings.get('jdk'))
ontology = Ontology(home, settings.get('ontology'))
kite.load(settings)
ontology.load(settings)
# sublime.save_settings('Kite.sublime-settings')
