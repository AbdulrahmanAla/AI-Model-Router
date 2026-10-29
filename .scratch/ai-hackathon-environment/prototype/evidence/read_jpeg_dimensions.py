from pathlib import Path


def dimensions(path: Path) -> tuple[int, int]:
	data = path.read_bytes()
	index = 2
	while index < len(data):
		if data[index] != 0xFF:
			index += 1
			continue
		marker = data[index + 1]
		index += 2
		if marker in (0xD8, 0xD9):
			continue
		length = int.from_bytes(data[index:index + 2], "big")
		if marker in (*range(0xC0, 0xC4), *range(0xC5, 0xC8), *range(0xC9, 0xCC), *range(0xCD, 0xD0)):
			height = int.from_bytes(data[index + 3:index + 5], "big")
			width = int.from_bytes(data[index + 5:index + 7], "big")
			return width, height
		index += length
	raise ValueError(f"No JPEG frame found in {path}")


for path in Path(__file__).parent.glob("*.jpg"):
	print(path.name, dimensions(path))
