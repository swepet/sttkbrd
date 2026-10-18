import os
import runpy
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
runpy.run_module("sttkbrd", run_name="__main__", alter_sys=True)
