from pathlib import Path
from openpyxl import Workbook

def main() -> None:
    out = Path(__file__).parent / "sample.xlsx"
    wb = Workbook()
    s1 = wb.active
    s1.title = "Specs"
    s1.append(["Name", "Value"])
    s1.append(["Vdd", "3.3V"])
    s1.append(["Freq", "168MHz"])
    s2 = wb.create_sheet("Notes")
    s2.append(["Item", "Detail"])
    s2.append(["MCU", "Cortex-M4"])
    wb.save(str(out))

if __name__ == "__main__":
    main()
