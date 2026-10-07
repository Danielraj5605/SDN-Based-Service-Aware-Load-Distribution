"""Append-only CSV logs (decisions and per-server metrics) for later analysis."""
import csv
import os


class CsvLog:
    def __init__(self, path, header):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        is_new = not os.path.exists(path) or os.path.getsize(path) == 0
        self._file = open(path, 'a', newline='')
        self._writer = csv.writer(self._file)
        if is_new:
            self.write(header)

    def write(self, row):
        self._writer.writerow(row)
        self._file.flush()
