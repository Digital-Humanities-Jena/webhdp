"""
Image Metadata Extractor Processor
Extracts comprehensive metadata from image files with privacy filtering
"""

from pathlib import Path
from typing import Union, Dict, Any, Optional
import json
import re
import string
from PIL import Image
from PIL.ExifTags import TAGS
import ftfy


class ImageMetadataProcessor:
    """Extracts metadata and EXIF data from image files"""

    def __init__(
        self,
        remove_address: bool = True,
        remove_mail: bool = True,
        include_technical_details: bool = True,
        readable_maker_notes_only: bool = True,
        version: str = "undefined",
    ):
        self.remove_address = remove_address
        self.remove_mail = remove_mail
        self.include_technical_details = include_technical_details
        self.readable_maker_notes_only = readable_maker_notes_only
        self.version = version

    def process(self, image_file: Union[str, Path]) -> Dict[str, Any]:
        """
        Extract metadata from image file

        Args:
            image_file: Path to image file

        Returns:
            Dict containing extraction results and metadata
        """
        image_path = Path(image_file)

        result = {
            "input_file": str(image_path),
            "file_exists": image_path.exists(),
            "success": True,
            "results": {},
            "errors": [],
            "warnings": [],
            "metadata": {
                "processor_version": self.version,
                "parameters_used": {
                    "remove_address": self.remove_address,
                    "remove_mail": self.remove_mail,
                    "include_technical_details": self.include_technical_details,
                    "readable_maker_notes_only": self.readable_maker_notes_only,
                },
            },
        }

        if not image_path.exists():
            result["errors"].append(f"Image file does not exist: {image_path}")
            result["success"] = False
            return result

        try:
            # Extract image metadata
            metadata = self._extract_image_metadata(image_path)
            if metadata:
                result["results"] = metadata
            else:
                result["errors"].append("Failed to extract metadata - file may not be a valid image")
                result["success"] = False

        except Exception as e:
            result["errors"].append(f"Error extracting metadata: {str(e)}")
            result["success"] = False

        # Set final success status
        result["success"] = len(result["errors"]) == 0

        return result

    def _extract_image_metadata(self, image_path: Path) -> Optional[Dict[str, Any]]:
        """
        Enhanced version of the original get_image_metadata function
        """
        try:
            # Basic file information
            filename = image_path.name
            filesize_kb = image_path.stat().st_size / 1024  # Bytes to Kilobytes

            with Image.open(image_path) as img:
                width, height = img.size
                megapixels = (width * height) / 1_000_000

                # Extract EXIF data
                exif_data = self._extract_exif_data(img)

                # Build metadata structure
                metadata = {
                    "basic_info": {
                        "filename": filename,
                        "filesize": f"{filesize_kb:.2f} KB",
                        "filesize_bytes": image_path.stat().st_size,
                        "width": width,
                        "height": height,
                        "aspect_ratio": round(width / height, 2) if height > 0 else 0,
                        "megapixels": f"{megapixels:.2f}",
                        "megapixels_numeric": round(megapixels, 2),
                        "format": img.format,
                        "mode": img.mode,
                    },
                    "exif_data": exif_data,
                    "privacy_applied": {"address_removed": self.remove_address, "email_removed": self.remove_mail},
                }

                # Add color profile information if available
                if hasattr(img, "info") and "icc_profile" in img.info:
                    metadata["basic_info"]["has_color_profile"] = True
                else:
                    metadata["basic_info"]["has_color_profile"] = False

                return metadata

        except Exception as e:
            raise Exception(f"Failed to process image file: {str(e)}")

    def _extract_exif_data(self, img: Image.Image) -> Dict[str, Any]:
        """Extract and process EXIF data from image"""
        exif_decoded_data = {}

        try:
            exif_data = img._getexif()
            if not exif_data:
                return {"exif_available": False, "data": {}}

            # Process EXIF data
            exif = {TAGS.get(k, k): self._decode_exif_string(v) for k, v in exif_data.items() if k in TAGS}

            for key, value in exif.items():
                # Skip empty or invalid values
                if str(value) == "{}":
                    continue

                # Handle MakerNote filtering
                if key == "MakerNote" and self.readable_maker_notes_only:
                    if not self._is_readable_string(value):
                        continue

                # Handle privacy-sensitive fields
                if key in ["Copyright", "Artist", "ImageDescription", "UserComment"]:
                    value = ftfy.fix_encoding(str(value))
                    original_value = value

                    if self.remove_address or self.remove_mail:
                        value = self._remove_personal_information(value, self.remove_address, self.remove_mail)
                        if value != original_value:
                            value += " [privacy filtered]"

                # Filter technical details if requested
                if not self.include_technical_details and key in self._get_technical_exif_keys():
                    continue

                exif_decoded_data[key] = ftfy.fix_encoding(str(value))

            # Organize EXIF data by category
            categorized_exif = self._categorize_exif_data(exif_decoded_data)

            return {
                "exif_available": True,
                "data": exif_decoded_data,
                "categorized": categorized_exif,
                "total_fields": len(exif_decoded_data),
            }

        except Exception as e:
            return {"exif_available": False, "error": str(e), "data": {}}

    def _decode_exif_string(self, value: Union[str, bytes]) -> str:
        """
        Decodes EXIF string values from bytes to UTF-8 or Latin-1 encoded strings
        """
        if isinstance(value, bytes):
            try:
                return value.decode("utf-8")
            except UnicodeDecodeError:
                try:
                    return value.decode("latin1")  # fallback
                except UnicodeDecodeError:
                    return value.decode("utf-8", errors="replace")  # force decode with replacement
        return str(value)

    def _is_readable_string(self, value: Union[bytes, str]) -> bool:
        """
        Determines if a given value is a readable string
        Enhanced version with better heuristics
        """
        threshold = 0.3  # Lowered threshold for better detection

        if isinstance(value, bytes):
            if len(value) == 0:
                return False

            # Count printable characters
            printable_count = sum(1 for b in value if 32 <= b <= 126 or b in [9, 10, 13])
            printable_ratio = printable_count / len(value)

            return printable_ratio >= threshold

        elif isinstance(value, str):
            if len(value) == 0:
                return False

            # Check for printable characters
            printable_count = sum(1 for char in value if char in string.printable)
            printable_ratio = printable_count / len(value)

            return printable_ratio >= threshold

        return False

    def _remove_personal_information(
        self, input_str: str, remove_address: bool = True, remove_mail: bool = True
    ) -> str:
        """
        Enhanced personal information removal with better patterns
        """
        # Replace common line break representations
        preprocessed_str = input_str.replace("\\n", ", ").replace("\n", ", ").replace("\r", ", ")

        if remove_address:
            # Enhanced street address patterns
            patterns = [
                r"\b\d+\s+[\w\s]+(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|Circle|Cir|Court|Ct|Place|Pl)\.?\b",
                r"\b[\w\s]+\s+\d+\b",  # Simple pattern for street name + number
                r"\b\d{5}(?:-\d{4})?\b",  # ZIP codes
                r"\b[A-Z]{2}\s+\d{5}\b",  # State + ZIP
            ]

            for pattern in patterns:
                preprocessed_str = re.sub(pattern, "", preprocessed_str, flags=re.IGNORECASE)

        if remove_mail:
            # Enhanced email patterns
            email_patterns = [
                r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",  # Standard email
                r"\b[A-Za-z0-9._%+-]+\s*@\s*[A-Za-z0-9.-]+\s*\.\s*[A-Z|a-z]{2,}\b",  # Email with spaces
            ]

            for pattern in email_patterns:
                preprocessed_str = re.sub(pattern, "", preprocessed_str)

        # Clean up multiple spaces and trailing punctuation
        cleaned_str = re.sub(r"\s+", " ", preprocessed_str)  # Collapse multiple spaces
        # Trim whitespace, then remove any leftover punctuation from the ends
        cleaned_str = cleaned_str.strip()
        cleaned_str = re.sub(r"^[.,;: ]+", "", cleaned_str)  # Leading punctuation
        cleaned_str = re.sub(r"[.,;: ]+$", "", cleaned_str)  # Trailing punctuation

        return cleaned_str.strip()

    def _get_technical_exif_keys(self) -> set:
        """Get set of technical EXIF field names"""
        return {
            "ExposureTime",
            "FNumber",
            "ExposureProgram",
            "ISOSpeedRatings",
            "ISO",
            "ExifVersion",
            "DateTimeOriginal",
            "DateTimeDigitized",
            "ShutterSpeedValue",
            "ApertureValue",
            "BrightnessValue",
            "ExposureBiasValue",
            "MaxApertureValue",
            "MeteringMode",
            "LightSource",
            "Flash",
            "FocalLength",
            "FocalLengthIn35mmFilm",
            "SubsecTime",
            "SubsecTimeOriginal",
            "SubsecTimeDigitized",
            "FlashPixVersion",
            "ColorSpace",
            "ExifImageWidth",
            "ExifImageHeight",
            "SensingMethod",
            "FileSource",
            "SceneType",
            "CFAPattern",
            "CustomRendered",
            "ExposureMode",
            "WhiteBalance",
            "DigitalZoomRatio",
            "SceneCaptureType",
            "GainControl",
            "Contrast",
            "Saturation",
            "Sharpness",
            "SubjectDistanceRange",
        }

    def _categorize_exif_data(self, exif_data: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """Categorize EXIF data for better organization"""
        categories = {
            "camera_info": {},
            "image_settings": {},
            "datetime": {},
            "location": {},
            "technical": {},
            "other": {},
        }

        # Define category mappings
        camera_keys = {"Make", "Model", "Software", "LensModel", "LensMake"}
        settings_keys = {
            "ExposureTime",
            "FNumber",
            "ISOSpeedRatings",
            "ISO",
            "FocalLength",
            "Flash",
            "WhiteBalance",
            "ExposureMode",
            "MeteringMode",
        }
        datetime_keys = {"DateTime", "DateTimeOriginal", "DateTimeDigitized"}
        location_keys = {"GPSInfo", "GPSLatitude", "GPSLongitude", "GPSAltitude"}

        for key, value in exif_data.items():
            if key in camera_keys:
                categories["camera_info"][key] = value
            elif key in settings_keys:
                categories["image_settings"][key] = value
            elif key in datetime_keys:
                categories["datetime"][key] = value
            elif key in location_keys:
                categories["location"][key] = value
            elif key in self._get_technical_exif_keys():
                categories["technical"][key] = value
            else:
                categories["other"][key] = value

        # Remove empty categories
        return {k: v for k, v in categories.items() if v}

    def save_results(self, results: Dict[str, Any], output_path: Path) -> None:
        """Save results to JSON file"""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
