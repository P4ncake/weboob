<%inherit file="layout.py"/>
from weboob.tools.test import BackendTest


class ${r.classname}Test(BackendTest):
    MODULE = '${r.name}'
