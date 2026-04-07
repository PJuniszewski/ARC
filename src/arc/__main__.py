"""Allow running ARC as a module: python -m arc"""
from arc.cli import main
import sys
sys.exit(main())
