#!/bin/bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" -y 
brew install numpy scipy ipython jupyter git 
git clone https://github.com/smartmanru/py-clubhouse ~/py-club
cd ~/py-club
python3 -m pip install -r requirements.txt
python3 -m pip install agora agora-python-sdk
python3 v2.py
