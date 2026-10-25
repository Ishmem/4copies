"""
HP PCL3 / PCL3GUI Command Generator.
Constructs valid HP DeskJet raster streams directly from the reverse-engineered GPD specifications.
Corresponds to commands defined in hpdj_2130.gpd:
- CmdBeginRaster: <1B>*v7S<1B>*r1A
- CmdEndRaster: <1B>*rC
- CmdSendBlockData: <1B>*b %d{NumOfDataBytes}"W"
- CmdCR (<0D>), CmdLF (<0A>), CmdFF (<0C>)
"""

from __future__ import annotations

import io
from typing import List, Tuple


class PCL3RasterGenerator:
    """
    Builds raw PCL3GUI print job streams ready for the Windows Spooler or direct USB pipe.
    """

    ESC = b"\x1b"
    CMD_RESET = b"\x1bE"
    CMD_UNIVERSAL_EXIT_LANGUAGE = b"\x1b%-12345X"
    CMD_ENTER_PCL = b"@PJL ENTER LANGUAGE=PCL3GUI\r\n"
    CMD_BEGIN_RASTER = b"\x1b*v7S\x1b*r1A"
    CMD_END_RASTER = b"\x1b*rC"
    CMD_FORM_FEED = b"\x0c"
    CMD_CR = b"\r"
    CMD_LF = b"\n"

    def __init__(self, resolution_dpi: int = 300):
        self.resolution_dpi = resolution_dpi
        self.buffer = io.BytesIO()

    def start_job(self, job_name: str = "Test Print Page") -> None:
        """Emits PJL (Printer Job Language) header and initializes PCL3GUI."""
        self.buffer.write(self.CMD_UNIVERSAL_EXIT_LANGUAGE)
        self.buffer.write(b"@PJL \r\n")
        self.buffer.write(f'@PJL JOB NAME="{job_name}"\r\n'.encode("ascii"))
        self.buffer.write(self.CMD_ENTER_PCL)
        self.buffer.write(self.CMD_RESET)

        # Set resolution (e.g. ESC * t 300 R)
        self.buffer.write(f"\x1b*t{self.resolution_dpi}R".encode("ascii"))

    def begin_page(self) -> None:
        """Starts the raster graphics session for a page."""
        self.buffer.write(self.CMD_BEGIN_RASTER)

    def send_raster_row(self, row_bytes: bytes) -> None:
        """
        Sends a single horizontal raster line.
        Format: ESC * b <NumOfDataBytes> W <data>
        """
        header = f"\x1b*b{len(row_bytes)}W".encode("ascii")
        self.buffer.write(header)
        self.buffer.write(row_bytes)

    def end_page(self) -> None:
        """Ends raster graphics and issues Form Feed (CmdFF)."""
        self.buffer.write(self.CMD_END_RASTER)
        self.buffer.write(self.CMD_FORM_FEED)

    def end_job(self) -> bytes:
        """Finalizes the job with reset and UEL."""
        self.buffer.write(self.CMD_RESET)
        self.buffer.write(self.CMD_UNIVERSAL_EXIT_LANGUAGE)
        return self.buffer.getvalue()

    @classmethod
    def generate_test_pattern(cls, width_dots: int = 300, height_dots: int = 150) -> bytes:
        """
        Generates a sample test page with a crosshatch/checker pattern.
        """
        gen = cls(resolution_dpi=300)
        gen.start_job("HP DeskJet Diagnostics Pattern")
        gen.begin_page()

        bytes_per_row = (width_dots + 7) // 8
        for y in range(height_dots):
            row = bytearray(bytes_per_row)
            # Create a striped diagnostic pattern
            for x_byte in range(bytes_per_row):
                if (y // 8) % 2 == 0:
                    row[x_byte] = 0xAA if x_byte % 2 == 0 else 0x55
                else:
                    row[x_byte] = 0xFF if (x_byte % 4 == 0 or y % 16 == 0) else 0x00
            gen.send_raster_row(bytes(row))

        gen.end_page()
        return gen.end_job()
