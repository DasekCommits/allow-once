#!/usr/bin/env python3
"""DataFlow Toolkit: clean and merge CSV files."""

import argparse


def main():
    parser = argparse.ArgumentParser(description="Clean and merge CSV files.")
    parser.add_argument("files", nargs="*", help="CSV files to process")
    parser.add_argument("--merge", action="store_true", help="merge into one file")
    args = parser.parse_args()

    if not args.files:
        parser.print_help()
        return
    print(f"Would process {len(args.files)} file(s). (demo build)")


if __name__ == "__main__":
    main()
