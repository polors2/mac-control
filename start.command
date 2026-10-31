#!/bin/zsh
cd -- "${0:A:h}"
/usr/bin/python3 service.py start && /usr/bin/open http://localhost:8765
