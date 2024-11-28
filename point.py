import xml.etree.ElementTree as ET

def check_yml_fields(xml_filepath):
    """
    Reads a YML XML file and checks for populated fields within <offer> elements.

    Args:
        xml_filepath: Path to the YML XML file.

    Returns:
        A dictionary where keys are offer IDs and values are lists of missing fields.
        Returns an empty dictionary if no errors are found or if the file is invalid.
    """

    try:
        tree = ET.parse(xml_filepath)
        root = tree.getroot()
        offers = root.find('shop').find('offers')
        if offers is None:
            return {} #Handle case where offers element is missing

        errors = {}
        required_fields = ['price', 'currencyId', 'categoryId', 'picture', 'name', 'vendor', 'description', 'barcode']

        for offer in offers.findall('offer'):
            offer_id = offer.get('id')
            missing_fields = []
            for field in required_fields:
                element = offer.find(field)
                if element is None or element.text is None or element.text.strip() == "":
                    missing_fields.append(field)
            if missing_fields:
                errors[offer_id] = missing_fields
        return errors

    except FileNotFoundError:
        print(f"Error: File not found at {xml_filepath}")
        return {}
    except ET.ParseError:
        print(f"Error: Invalid XML file at {xml_filepath}")
        return {}
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return {}


if __name__ == "__main__":
    xml_file = "yandex_feed.xml"  # Replace with your XML file path
    missing_data = check_yml_fields(xml_file)

    if missing_data:
        print("Errors found in the following offers:")
        for offer_id, missing_fields in missing_data.items():
            print(f"Offer ID: {offer_id}, Missing fields: {', '.join(missing_fields)}")
    else:
        print("No errors found in the YML file.")
