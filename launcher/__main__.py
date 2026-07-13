#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Allow `python -m launcher` to invoke the entry point."""
from launcher.entry import main
import sys
sys.exit(main())
