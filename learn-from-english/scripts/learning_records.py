#!/usr/bin/env python3
"""Compatibility entry point for the learning-record command-line tool."""

from learning_records_tool.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
