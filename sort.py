import json
import re

def extract_lesson_number(topic):
    """Extract the lesson number from a topic string like 'Lekcja 29' or 'Lekcja 24pdf'."""
    match = re.search(r'Lekcja\s+(\d+)', topic)
    if match:
        return int(match.group(1))
    return 0


def sort_lessons(input_file='material/polskionlinepro.json', output_file=None):
    """
    Sort lessons in the JSON file by lesson number.

    Args:
        input_file: Path to the input JSON file
        output_file: Path to the output JSON file (defaults to input_file to overwrite)
    """
    if output_file is None:
        output_file = input_file

    # Read the JSON file
    with open(input_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Sort the data array by lesson number
    if 'data' in data and isinstance(data['data'], list):
        data['data'].sort(key=lambda x: extract_lesson_number(x.get('topic', '')))

    # Write the sorted data back
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

    print(f"Sorted lessons and saved to {output_file}")


if __name__ == '__main__':
    sort_lessons()

