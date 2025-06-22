"""
WadWyrm is a standalone utility script that locates the WADS in Wizard101 (source_dir).
It Worms it way through the GameData folder extracting all the WADS into subdirectories
folders loaded under (dest_dir.) This script is just for analysis/useful for WadWatcher.
WadWatcher needs the extracted Wads so we can use normal "search by file" in Windows
explorer or the Everything tool by Voidtools. We use this to determine the pattern
of where the WAD is located. Then we can update the Collision parser to also find
that collision nif file.
"""

import os
import subprocess
import wizwad
from pathlib import Path


def extract_using_cli():
    """Extract WAD files using wizwad command line interface"""
    source_dir = Path(r"C:\ProgramData\KingsIsle Entertainment\Wizard101\Data\GameData")
    dest_dir = Path(r"C:\Wizwad\AllGameData")

    # Create destination directory if it doesn't exist
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Check if source directory exists
    if not source_dir.exists():
        print(f"Error: Source directory does not exist: {source_dir}")
        return

    # Find all WAD files in the source directory
    wad_files = list(source_dir.glob("*.wad"))

    if not wad_files:
        print(f"No WAD files found in {source_dir}")
        return

    print(f"Found {len(wad_files)} WAD files to extract using CLI method...")

    for wad_file in wad_files:
        try:
            print(f"\nProcessing: {wad_file.name}")

            # Create subdirectory for this WAD file (without .wad extension)
            wad_name = wad_file.stem
            wad_output_dir = dest_dir / wad_name
            wad_output_dir.mkdir(exist_ok=True)

            # Use wizwad CLI to extract
            cmd = ["wizwad", "extract", str(wad_file), str(wad_output_dir)]
            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode == 0:
                print(f"  Successfully extracted to: {wad_output_dir}")
                if result.stdout:
                    print(f"  Output: {result.stdout.strip()}")
            else:
                print(f"  Error extracting: {result.stderr}")

        except Exception as e:
            print(f"Error processing {wad_file.name}: {e}")
            continue

    print(f"\nExtraction complete! Files extracted to: {dest_dir}")


def extract_using_extract_all():
    """Extract WAD files using the built-in extract_all method (fastest)"""
    source_dir = Path(r"C:\ProgramData\KingsIsle Entertainment\Wizard101\Data\GameData")
    dest_dir = Path(r"C:\Wizwad\AllGameData")

    # Create destination directory if it doesn't exist
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Check if source directory exists
    if not source_dir.exists():
        print(f"Error: Source directory does not exist: {source_dir}")
        return

    # Find all WAD files in the source directory
    wad_files = list(source_dir.glob("*.wad"))

    if not wad_files:
        print(f"No WAD files found in {source_dir}")
        return

    print(f"Found {len(wad_files)} WAD files to extract using extract_all method...")

    for wad_file in wad_files:
        try:
            print(f"\nProcessing: {wad_file.name}")

            # Create subdirectory for this WAD file (without .wad extension)
            wad_name = wad_file.stem
            wad_output_dir = dest_dir / wad_name
            wad_output_dir.mkdir(exist_ok=True)

            # Open the WAD file and extract all at once
            wad = wizwad.Wad(str(wad_file))

            print(f"  Contains {len(wad.name_list())} files")
            print(f"  Extracting all files to: {wad_output_dir}")

            # Use the built-in extract_all method
            wad.extract_all(str(wad_output_dir))

            print(f"  Successfully extracted all files!")

            # Close the WAD file
            wad.close()

        except Exception as e:
            print(f"Error processing {wad_file.name}: {e}")
            continue

    print(f"\nExtraction complete! Files extracted to: {dest_dir}")

    """Extract WAD files using Python API with dynamic method detection"""
    source_dir = Path(r"C:\ProgramData\KingsIsle Entertainment\Wizard101\Data\GameData")
    dest_dir = Path(r"C:\Wizwad\AllGameData")

    # Create destination directory if it doesn't exist
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Check if source directory exists
    if not source_dir.exists():
        print(f"Error: Source directory does not exist: {source_dir}")
        return

    # Find all WAD files in the source directory
    wad_files = list(source_dir.glob("*.wad"))

    if not wad_files:
        print(f"No WAD files found in {source_dir}")
        return

    print(f"Found {len(wad_files)} WAD files to extract using Python API...")

    for wad_file in wad_files:
        try:
            print(f"\nProcessing: {wad_file.name}")

            # Create subdirectory for this WAD file (without .wad extension)
            wad_name = wad_file.stem
            wad_output_dir = dest_dir / wad_name
            wad_output_dir.mkdir(exist_ok=True)

            # Open the WAD file
            wad = wizwad.Wad(str(wad_file))

            # Get the list of files using the correct API
            file_list = wad.name_list()
            print(f"  Contains {len(file_list)} files")

            # Extract each file
            extracted_count = 0
            for file_name in file_list:
                try:
                    # Get the file data
                    file_data = wad.read(file_name)

                    # Create output path (preserve directory structure if any)
                    output_path = wad_output_dir / file_name

                    # Create parent directories if needed
                    output_path.parent.mkdir(parents=True, exist_ok=True)

                    # Write the file
                    with open(output_path, 'wb') as f:
                        f.write(file_data)

                    extracted_count += 1

                except Exception as e:
                    print(f"    Error extracting {file_name}: {e}")
                    continue

            print(f"  Successfully extracted {extracted_count}/{len(file_list)} files to: {wad_output_dir}")

            # Close the WAD file
            wad.close()

        except Exception as e:
            print(f"Error processing {wad_file.name}: {e}")
            continue

    print(f"\nExtraction complete! Files extracted to: {dest_dir}")


def debug_wad_api():
    """Debug the wizwad API to understand available methods"""
    source_dir = Path(r"C:\ProgramData\KingsIsle Entertainment\Wizard101\Data\GameData")

    wad_files = list(source_dir.glob("*.wad"))
    if not wad_files:
        print("No WAD files found for debugging")
        return

    test_wad = wad_files[0]
    print(f"Debugging with: {test_wad.name}")

    try:
        wad = wizwad.Wad(str(test_wad))

        print(f"\nWad object type: {type(wad)}")
        print(f"Available attributes: {[attr for attr in dir(wad) if not attr.startswith('_')]}")

        # Test each attribute
        for attr_name in dir(wad):
            if not attr_name.startswith('_'):
                try:
                    attr = getattr(wad, attr_name)
                    print(f"\n{attr_name}: {type(attr)}")

                    if callable(attr):
                        try:
                            # Try calling with no arguments
                            result = attr()
                            print(f"  {attr_name}() returned: {type(result)}")
                            if hasattr(result, '__len__'):
                                print(f"  Length: {len(result)}")
                            if hasattr(result, '__iter__') and len(result) > 0:
                                items = list(result)
                                print(f"  First few items: {items[:3]}")
                        except Exception as e:
                            print(f"  Error calling {attr_name}(): {e}")
                    else:
                        print(f"  Value: {attr}")
                        if hasattr(attr, '__len__'):
                            print(f"  Length: {len(attr)}")
                        if hasattr(attr, '__iter__'):
                            try:
                                items = list(attr)
                                print(f"  Items: {items[:3] if len(items) > 3 else items}")
                            except:
                                pass

                except Exception as e:
                    print(f"Error accessing {attr_name}: {e}")

        if hasattr(wad, 'close'):
            wad.close()

    except Exception as e:
        print(f"Error debugging WAD: {e}")


def main():
    # Check if wizwad is available
    try:
        import wizwad
    except ImportError:
        print("wizwad not found. Install it with: pip install wizwad")
        return

    print("Using a decent computer this took me 10 minutes to run and it was doing 100MBps and exported about 13GBs of data")
    print("Choose extraction method:")
    print("1. Built-in extract_all (fastest, recommended)")
    print("2. Command Line Interface")
    print("3. Debug WAD API first")

    choice = input("Enter choice (1-3): ").strip()

    if choice == "1":
        extract_using_extract_all()
    elif choice == "2":
        extract_using_cli()
    elif choice == "3":
        debug_wad_api()
    else:
        print("Invalid choice. Using extract_all method...")
        extract_using_extract_all()


if __name__ == "__main__":
    main()