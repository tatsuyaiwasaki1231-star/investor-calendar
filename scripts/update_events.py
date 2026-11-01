#!/usr/bin/env python3
"""Legacy FRED importer disabled for the public GitHub Pages calendar.

FRED API terms restrict storing, caching, archiving and redistribution of
API content. The public site must not copy FRED response data into JSON.
This script intentionally does not access FRED or use the FRED_API_KEY secret.
See https://fred.stlouisfed.org/legal/ for current terms.
"""

def main():
    print("FRED API disabled for the public calendar: no download, cache or redistribution.")

if __name__ == "__main__":
    main()
