"""
Comprehensive DEBUG WAD File Pattern Analysis Script for BestQuest.py!
Analyzes all patterns in scanned_assets.txt to determine where NIF files are stored
"""

import sys
import csv
from pathlib import Path
from collections import defaultdict, Counter
import re

# Base paths
GAME_DATA_PATH = Path(r"C:\ProgramData\KingsIsle Entertainment\Wizard101\Data\GameData")
EXTRACTED_DATA_PATH = Path(r"C:\Wizwad\AllGameData")
SCANNED_ASSETS_PATH = Path(r"C:\Github Repos Python/QuestWhiz/asset logs/scanned_assets.txt")
HOW_MANY_NIFFS = 200
# EXTRACTED_DATA_PATH = Path(r"/mnt/c/Wizwad/AllGameData")
# SCANNED_ASSETS_PATH = Path(r"/mnt/c/Github Repos Python/QuestWhiz/asset logs/scanned_assets.txt")

class AssetPatternAnalyzer:
    def __init__(self):
        self.assets = []
        self.unique_nifs = {}  # nif_filename -> [asset_data_list]
        self.found_paths = {}  # nif_filename -> found_path_in_extracted_data
        self.patterns = defaultdict(list)
        
    def load_scanned_assets(self):
        """Load all assets from scanned_assets.txt"""
        print("Loading scanned assets...")
        
        with open(SCANNED_ASSETS_PATH, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                
                parts = line.split(',')
                if len(parts) != 3:
                    print(f"Warning: Skipping malformed line {line_num}: {line}")
                    continue
                
                entity_name, asset_path, zone_name = parts
                
                # Extract just the .nif filename
                nif_filename = Path(asset_path).name
                if not nif_filename.endswith('.nif'):
                    print(f"Warning: Non-NIF asset at line {line_num}: {asset_path}")
                    continue
                
                asset_data = {
                    'entity_name': entity_name,
                    'asset_path': asset_path,
                    'zone_name': zone_name,
                    'nif_filename': nif_filename,
                    'line_num': line_num
                }
                
                self.assets.append(asset_data)
                
                # Group by NIF filename for deduplication
                if nif_filename not in self.unique_nifs:
                    self.unique_nifs[nif_filename] = []
                self.unique_nifs[nif_filename].append(asset_data)
        
        print(f"Loaded {len(self.assets)} total assets")
        print(f"Found {len(self.unique_nifs)} unique NIF filenames")
        
    def search_extracted_data(self):
        """Search for each unique NIF file in the extracted data"""
        print(f"\nSearching for NIF files in {EXTRACTED_DATA_PATH}...")
        
        if not EXTRACTED_DATA_PATH.exists():
            print(f"ERROR: Extracted data path does not exist: {EXTRACTED_DATA_PATH}")
            return
        
        # First, let's take a sample if there are too many files to process
        nif_list = list(self.unique_nifs.keys())
        total_nifs = len(nif_list)
        
        # If we have more than X unique NIFs, sample them for faster analysis
        if total_nifs > HOW_MANY_NIFFS:
            print(f"Found {total_nifs} unique NIF files. Taking a sample of 50 for faster analysis...")
            import random
            nif_list = random.sample(nif_list, HOW_MANY_NIFFS)
        
        print(f"Searching for {len(nif_list)} NIF files...")
        
        found_count = 0
        not_found = []
        
        for i, nif_filename in enumerate(nif_list, 1):
            print(f"[{i}/{len(nif_list)}] Searching for: {nif_filename}")
            
            # Search recursively for the file
            matches = list(EXTRACTED_DATA_PATH.rglob(nif_filename))
            
            if matches:
                # Use the first match (there might be duplicates)
                found_path = matches[0]
                self.found_paths[nif_filename] = found_path
                found_count += 1
                
                # Get relative path from AllGameData root for analysis
                relative_path = found_path.relative_to(EXTRACTED_DATA_PATH)
                print(f"  ✓ Found: {relative_path}")
                
                if len(matches) > 1:
                    print(f"    Note: Found {len(matches)} copies")
            else:
                not_found.append(nif_filename)
                print(f"  ✗ NOT FOUND: {nif_filename}")
        
        print(f"\nSearch Results:")
        print(f"  Found: {found_count}/{len(nif_list)}")
        print(f"  Not found: {len(not_found)}")
        
        if total_nifs > len(nif_list):
            print(f"  Note: This was a sample of {len(nif_list)} out of {total_nifs} total unique NIF files")
        
        if not_found:
            print(f"\nMissing files:")
            for nif in not_found[:10]:  # Show first 10
                print(f"  - {nif}")
            if len(not_found) > 10:
                print(f"  ... and {len(not_found) - 10} more")
            
            # Log detailed info about failed files for manual search
            print(f"\n=== FAILED FILES FOR MANUAL SEARCH ===")
            for nif_filename in not_found:
                asset_entries = self.unique_nifs[nif_filename]
                print(f"\nFile: {nif_filename}")
                for entry in asset_entries:
                    print(f"  Entity: {entry['entity_name']}")
                    print(f"  Asset Path: {entry['asset_path']}")
                    print(f"  Zone: {entry['zone_name']}")
                    print(f"  Pattern: {self.categorize_asset_path(entry['asset_path'])}")
                print(f"  → Please search for '{nif_filename}' in AllGameData and report back!")
                
    def analyze_patterns(self):
        """Analyze the patterns between asset paths and found file locations"""
        print(f"\n=== PATTERN ANALYSIS ===")
        
        pattern_matches = defaultdict(list)
        
        for nif_filename, found_path in self.found_paths.items():
            # Get all asset entries that use this NIF
            asset_entries = self.unique_nifs[nif_filename]
            
            # Get the directory structure from AllGameData
            relative_path = found_path.relative_to(EXTRACTED_DATA_PATH)
            directory_parts = relative_path.parent.parts
            
            for asset_entry in asset_entries:
                asset_path = asset_entry['asset_path']
                zone_name = asset_entry['zone_name']
                
                # Categorize the asset path pattern
                pattern_type = self.categorize_asset_path(asset_path)
                
                pattern_data = {
                    'asset_path': asset_path,
                    'found_path': str(relative_path),
                    'directory_parts': directory_parts,
                    'zone_name': zone_name,
                    'entity_name': asset_entry['entity_name']
                }
                
                pattern_matches[pattern_type].append(pattern_data)
        
        # Analyze each pattern type
        for pattern_type, matches in pattern_matches.items():
            print(f"\n--- {pattern_type} Pattern ({len(matches)} matches) ---")
            
            # Find common directory patterns
            dir_counter = Counter()
            for match in matches:
                if match['directory_parts']:
                    dir_counter[match['directory_parts'][0]] += 1
            
            print("Common root directories:")
            for root_dir, count in dir_counter.most_common(5):
                print(f"  {root_dir}: {count} files")
            
            # Show a few examples
            print("Examples:")
            for match in matches[:3]:
                print(f"  Asset: {match['asset_path']}")
                print(f"  Found: {match['found_path']}")
                print(f"  Zone:  {match['zone_name']}")
                print()
    
    def categorize_asset_path(self, asset_path):
        """Categorize an asset path to determine its pattern type"""
        if asset_path.startswith('|') and '|' in asset_path[1:]:
            # Pipe-delimited format
            parts = asset_path.split('|')
            if len(parts) >= 2:
                archive_name = parts[1]
                return f"PipeDelimited_{archive_name}"
            else:
                return "PipeDelimited_Unknown"
        elif asset_path.startswith('StateObjects/'):
            return "StateObjects"
        elif '/' in asset_path:
            # Direct path with no prefix
            return "DirectPath"
        else:
            return "Unknown"
    
    def generate_search_patterns(self):
        """Generate reusable search patterns based on the analysis"""
        print(f"\n=== GENERATED SEARCH PATTERNS ===")
        
        if not self.found_paths:
            print("No data to generate patterns from.")
            return
        
        # Group by pattern type for rule generation
        pattern_rules = defaultdict(lambda: defaultdict(list))
        
        for nif_filename, found_path in self.found_paths.items():
            asset_entries = self.unique_nifs[nif_filename]
            relative_path = found_path.relative_to(EXTRACTED_DATA_PATH)
            
            for asset_entry in asset_entries:
                asset_path = asset_entry['asset_path']
                pattern_type = self.categorize_asset_path(asset_path)
                
                # Extract the directory where the file was found
                found_dir = str(relative_path.parent)
                
                pattern_rules[pattern_type][found_dir].append({
                    'asset_path': asset_path,
                    'nif_filename': nif_filename,
                    'zone': asset_entry['zone_name']
                })
        
        # Generate rules for each pattern type
        for pattern_type, dir_mappings in pattern_rules.items():
            print(f"\n--- {pattern_type} Rules ---")
            
            if pattern_type.startswith("PipeDelimited_"):
                archive_name = pattern_type.replace("PipeDelimited_", "")
                print(f"Rule: |{archive_name}|WorldData|path → look in {archive_name}-WorldData.wad")
                
                # Show most common directories for this pattern
                print("Most common directories in extracted data:")
                for found_dir, examples in sorted(dir_mappings.items(), key=lambda x: len(x[1]), reverse=True)[:5]:
                    print(f"  {found_dir} ({len(examples)} files)")
                    
            elif pattern_type == "StateObjects":
                print("Rule: StateObjects/path → look in [ZoneName]-WorldData.wad")
                print("Most common directories in extracted data:")
                for found_dir, examples in sorted(dir_mappings.items(), key=lambda x: len(x[1]), reverse=True)[:5]:
                    print(f"  {found_dir} ({len(examples)} files)")
                    
            elif pattern_type == "DirectPath":
                print("Rule: Direct path with no prefix → location varies, check these directories:")
                for found_dir, examples in sorted(dir_mappings.items(), key=lambda x: len(x[1]), reverse=True)[:10]:
                    print(f"  {found_dir} ({len(examples)} files)")
                    # Show example zones for this directory
                    zones = set(ex['zone'] for ex in examples)
                    if len(zones) <= 3:
                        print(f"    Zones: {', '.join(zones)}")
                    else:
                        print(f"    Used in {len(zones)} different zones")
        
        print(f"\n=== SUMMARY FOR WAD FILE SEARCHING ===")
        print("Based on the analysis, here's how to find NIF files:")
        print()
        
        # Create a practical search function template
        print("def find_nif_in_wad(asset_path, zone_name):")
        print("    \"\"\"Find which WAD file contains a NIF based on its asset path\"\"\"")
        print("    if asset_path.startswith('|') and '|' in asset_path[1:]:")
        print("        # Pipe-delimited format: |ArchiveName|WorldData|path")
        print("        parts = asset_path.split('|')")
        print("        if len(parts) >= 2:")
        print("            archive_name = parts[1]")
        print("            return f'{archive_name}-WorldData.wad'")
        print("    elif asset_path.startswith('StateObjects/'):")
        print("        # StateObjects: use zone-specific WorldData WAD")
        print("        root_zone = zone_name.split('/')[0]")
        print("        return f'{root_zone}-WorldData.wad'")
        print("    else:")
        print("        # Direct path: may need to search multiple WADs")
        print("        # Check zone-specific WAD first, then common ones")
        print("        root_zone = zone_name.split('/')[0]")
        print("        candidates = [f'{root_zone}-WorldData.wad', 'Mob-WorldData.wad', '_Shared-WorldData.wad']")
        print("        return candidates")
        print()
        
    def run_analysis(self):
        """Run the complete analysis"""
        try:
            self.load_scanned_assets()
            self.search_extracted_data()
            self.analyze_patterns()
            self.generate_search_patterns()
        except Exception as e:
            print(f"Error during analysis: {e}")
            import traceback
            traceback.print_exc()


def main():
    """Main function to run the comprehensive analysis"""
    print("=== Comprehensive WAD File Pattern Analysis ===\n")
    
    analyzer = AssetPatternAnalyzer()
    analyzer.run_analysis()


if __name__ == "__main__":
    main()