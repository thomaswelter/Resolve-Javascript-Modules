#!c:\users\thomas\appdata\local\programs\python\python37-32\python.exe
# EASY-INSTALL-ENTRY-SCRIPT: 'esprima==4.0.1','console_scripts','esprima'
__requires__ = 'esprima==4.0.1'
import re
import sys
from pkg_resources import load_entry_point

if __name__ == '__main__':
    sys.argv[0] = re.sub(r'(-script\.pyw?|\.exe)?$', '', sys.argv[0])
    sys.exit(
        load_entry_point('esprima==4.0.1', 'console_scripts', 'esprima')()
    )
