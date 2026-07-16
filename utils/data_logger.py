import csv
import os
import cv2
import numpy as np
from datetime import datetime

class DataLogger:
    """
    Handles exporting table data to CSV and saving frames to disk.
    """
    def __init__(self, export_dir="exports"):
        self.export_dir = export_dir
        if not os.path.exists(self.export_dir):
            os.makedirs(self.export_dir)
            
    def export_csv(self, filename: str, headers: list, data: list):
        """
        Exports a 2D list of data to a CSV file.
        """
        filepath = os.path.join(self.export_dir, filename)
        try:
            with open(filepath, mode='w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(headers)
                writer.writerows(data)
            return filepath
        except Exception as e:
            print(f"Failed to export CSV: {e}")
            return None

    def save_frame(self, filename: str, frame: np.ndarray):
        """
        Saves a numpy array frame as an image file.
        """
        filepath = os.path.join(self.export_dir, filename)
        try:
            cv2.imwrite(filepath, frame)
            return filepath
        except Exception as e:
            print(f"Failed to save frame: {e}")
            return None
