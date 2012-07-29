What is this
============
A set of Sublime Text plugins / completions for Palantir Kite XML files.  This should be a bit more lightweight than eclipse.

Setup
-----
This does it's best to find everything in advance.

* Java command line tools will use what's on the path by default.  
* On Windows, if Quickstart is installed, it'll use the most recent version as the home - otherwise, it'll use the most recently run Workspace installation.
* Unix variants will attempt to use the default installation directory.

Hit Cmd/Ctrl-Shift-P, and pick "Palantir: Refresh Kite/Ontology", wait a few seconds, and go back to the palette and pick "Palantir: Save settings".

Completions
-----------
* Row processor / provider class names
* Parameters
* Ontology URIs

TODO
----
* Problems between scope and replacing the entire attribute value (empty attributes & end of attributes are problems)
* Verify ontology output
* Steal ontology from existing kite
* Parsing done in background queue
* More static sublime-completions (rewrite completions based on kite / ontology output?)
* Parse kite jars as trees 
* Schema validation on save
* Parse Kite / ontology on first load

DONE
----
* Locate appropriate jars
* Parse jar / javap output
* Cache kite / ontology for quicker loading
* Kite XML Language (for easier parsing of scope)

Copyright / license
-------------------
Released under Creative Commons CC-0 (as close to public domain as allowed by law): http://creativecommons.org/publicdomain/zero/1.0/