"""
File Integrity Validation Processor
Core logic for validating various file types
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import json
import magic
from PIL import Image
import PyPDF2
import wave
import mutagen
import os
import stat
import subprocess


class FileIntegrityProcessor:
    """Handles file integrity validation for various file types"""

    def __init__(self):
        self.mime_detector = magic.Magic(mime=True)

    def validate(self, filepath: Union[str, Path]) -> Dict[str, Any]:
        """
        Validates a file and returns comprehensive validation report
        Enhanced with permission and quarantine handling
        """
        filepath = Path(filepath)

        result = {
            "file_path": str(filepath),
            "file_exists": filepath.exists(),
            "file_type": None,
            "is_valid": True,
            "errors": [],
            "warnings": [],
            "validation_details": {},
            "component_version": "0.1.0",
        }

        # Check if file exists
        if not filepath.exists():
            result["errors"].append(f"File does not exist: {filepath}")
            result["is_valid"] = False
            result["validation_details"]["error_type"] = "file_not_found"
            return result

        # Enhanced permission and access checks
        access_check = self._check_file_access(filepath, result)
        if not access_check["can_proceed"]:
            result["is_valid"] = False
            return result

        try:
            # Get file type with enhanced error handling
            file_type = self._safe_get_file_type(filepath, result)
            if file_type:
                result["file_type"] = file_type
                result["validation_details"]["mime_type"] = file_type

                # Get file size safely
                try:
                    result["validation_details"]["file_size"] = filepath.stat().st_size
                except (OSError, PermissionError) as e:
                    result["warnings"].append(f"Could not get file size: {str(e)}")

                # Perform type-specific validation
                if file_type.startswith("image"):
                    self._validate_image(filepath, result)
                elif file_type == "application/pdf":
                    self._validate_pdf(filepath, result)
                elif file_type == "application/json":
                    self._validate_json(filepath, result)
                elif file_type.startswith("audio"):
                    self._validate_audio(filepath, result, file_type)
                else:
                    self._validate_generic(filepath, result)

        except Exception as e:
            result["errors"].append(f"Validation error: {str(e)}")
            result["is_valid"] = False
            result["validation_details"]["validation_exception"] = str(e)

        # Set overall validity (warnings don't make file invalid)
        result["is_valid"] = len(result["errors"]) == 0

        return result

    def process_directory(self, dirpath: Union[str, Path]) -> List[Dict[str, Any]]:
        """
        Validates all files in a directory and returns a list of reports.

        Args:
            dirpath: The path to the directory to process.

        Returns:
            A list of validation report dictionaries, one for each file.
        """
        dir_path = Path(dirpath)
        all_results = []

        if not dir_path.is_dir():
            # Return an empty list or raise an error if the path is not a valid directory
            error_report = {
                "file_path": str(dir_path),
                "file_exists": dir_path.exists(),
                "file_type": "directory",
                "is_valid": False,
                "errors": [f"Input path is not a valid directory: {dir_path}"],
                "validation_details": {"error_type": "invalid_input_directory"},
            }
            return [error_report]

        # Iterate over files, ignoring subdirectories
        for entry in sorted(dir_path.iterdir()):
            if entry.is_file():
                # Reuse the existing validation logic for each file
                file_report = self.validate(entry)
                all_results.append(file_report)

        return all_results

    def _check_file_access(self, filepath: Path, result: Dict[str, Any]) -> Dict[str, Any]:
        """Enhanced file access checking with macOS-specific handling"""
        access_info = {"can_proceed": True, "permission_issues": [], "quarantine_detected": False}

        try:
            # Check basic file permissions
            file_stat = filepath.stat()
            file_mode = file_stat.st_mode

            # Check if file is readable
            if not os.access(filepath, os.R_OK):
                access_info["permission_issues"].append("File not readable")
                result["errors"].append(f"Permission denied: File is not readable")
                access_info["can_proceed"] = False

            # Check for macOS quarantine (extended attributes)
            quarantine_status = self._check_macos_quarantine(filepath)
            if quarantine_status["is_quarantined"]:
                access_info["quarantine_detected"] = True
                result["warnings"].append("File is quarantined by macOS - validation may be limited")
                result["validation_details"]["quarantine_info"] = quarantine_status

                # Try to handle quarantine
                if self._attempt_quarantine_resolution(filepath, result):
                    result["warnings"].append("Quarantine resolved - proceeding with validation")
                else:
                    result["errors"].append("Cannot access quarantined file - validation blocked")
                    access_info["can_proceed"] = False

            # Add permission details to validation
            result["validation_details"]["file_permissions"] = {
                "owner_readable": bool(file_mode & stat.S_IRUSR),
                "group_readable": bool(file_mode & stat.S_IRGRP),
                "other_readable": bool(file_mode & stat.S_IROTH),
                "file_mode": oct(file_mode),
            }

        except (OSError, PermissionError) as e:
            result["errors"].append(f"Cannot access file metadata: {str(e)}")
            access_info["can_proceed"] = False

        return access_info

    def _check_macos_quarantine(self, filepath: Path) -> Dict[str, Any]:
        """Check if file is quarantined by macOS"""
        quarantine_info = {"is_quarantined": False, "quarantine_attributes": None, "check_method": "xattr"}

        try:
            # Check for quarantine extended attributes
            result = subprocess.run(["xattr", "-l", str(filepath)], capture_output=True, text=True, timeout=5)

            if result.returncode == 0 and "com.apple.quarantine" in result.stdout:
                quarantine_info["is_quarantined"] = True
                quarantine_info["quarantine_attributes"] = result.stdout

        except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
            # Fallback: try to detect via file access patterns
            try:
                with open(filepath, "rb") as f:
                    f.read(1)  # Try to read first byte
            except PermissionError as e:
                if "Operation not permitted" in str(e):
                    quarantine_info["is_quarantined"] = True
                    quarantine_info["check_method"] = "access_pattern"

        return quarantine_info

    def _attempt_quarantine_resolution(self, filepath: Path, result: Dict[str, Any]) -> bool:
        """Attempt to resolve macOS quarantine (if possible)"""
        try:
            # Method 1: Try removing quarantine attributes
            subprocess.run(["xattr", "-d", "com.apple.quarantine", str(filepath)], capture_output=True, timeout=5)

            # Test if file is now accessible
            with open(filepath, "rb") as f:
                f.read(1)

            result["validation_details"]["quarantine_resolved"] = True
            return True

        except (subprocess.TimeoutExpired, PermissionError, FileNotFoundError, Exception):
            # Method 2: Suggest user action
            result["validation_details"]["quarantine_resolution_suggestion"] = (
                "Run: xattr -d com.apple.quarantine '" + str(filepath) + "'"
            )
            return False

    def _safe_get_file_type(self, filepath: Path, result: Dict[str, Any]) -> Optional[str]:
        """Safely get file MIME type with fallback methods"""

        # Method 1: Try python-magic
        try:
            file_type = self.mime_detector.from_file(str(filepath))
            result["validation_details"]["mime_detection_method"] = "python-magic"
            return file_type
        except (PermissionError, OSError) as e:
            result["warnings"].append(f"python-magic failed due to permissions: {str(e)}")
        except Exception as e:
            result["warnings"].append(f"python-magic failed: {str(e)}")

        # Method 2: Try system 'file' command
        try:
            result_cmd = subprocess.run(
                ["file", "--mime-type", "-b", str(filepath)], capture_output=True, text=True, timeout=10
            )

            if result_cmd.returncode == 0:
                file_type = result_cmd.stdout.strip()
                result["validation_details"]["mime_detection_method"] = "system_file_command"
                return file_type
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
            result["warnings"].append(f"System file command failed: {str(e)}")

        # Method 3: Fallback to file extension
        extension_mapping = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".pdf": "application/pdf",
            ".json": "application/json",
            ".mp3": "audio/mpeg",
            ".wav": "audio/wav",
            ".txt": "text/plain",
            ".csv": "text/csv",
        }

        file_ext = filepath.suffix.lower()
        if file_ext in extension_mapping:
            file_type = extension_mapping[file_ext]
            result["validation_details"]["mime_detection_method"] = "file_extension_fallback"
            result["warnings"].append("Using file extension for type detection - may be inaccurate")
            return file_type

        result["warnings"].append("Could not determine file type - validation limited")
        result["validation_details"]["mime_detection_method"] = "failed"
        return None

    def _validate_image(self, filepath: Path, result: Dict[str, Any]) -> None:
        """Validate image file and update result"""
        try:
            with Image.open(filepath) as img:
                img.verify()
                # Reopen to get details (verify() closes the file)
                with Image.open(filepath) as img:
                    result["validation_details"].update(
                        {
                            "image_format": img.format,
                            "image_mode": img.mode,
                            "image_size": list(img.size),
                            "has_transparency": "transparency" in img.info,
                        }
                    )
        except Exception as e:
            result["errors"].append(f"Invalid image file: {str(e)}")

    def _validate_pdf(self, filepath: Path, result: Dict[str, Any]) -> None:
        """Validate PDF file and update result"""
        try:
            with open(filepath, "rb") as f:
                pdf_reader = PyPDF2.PdfReader(f)
                result["validation_details"].update(
                    {
                        "pdf_pages": len(pdf_reader.pages),
                        "pdf_encrypted": pdf_reader.is_encrypted,
                        "pdf_metadata": dict(pdf_reader.metadata) if pdf_reader.metadata else {},
                    }
                )
        except Exception as e:
            result["errors"].append(f"Invalid PDF file: {str(e)}")

    def _validate_json(self, filepath: Path, result: Dict[str, Any]) -> None:
        """Validate JSON file and update result"""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                result["validation_details"].update(
                    {
                        "json_structure": type(data).__name__,
                        "json_keys": list(data.keys()) if isinstance(data, dict) else None,
                        "json_length": len(data) if isinstance(data, (list, dict)) else None,
                    }
                )
        except json.JSONDecodeError as e:
            result["errors"].append(f"Invalid JSON file: {str(e)}")
        except Exception as e:
            result["errors"].append(f"Error reading JSON file: {str(e)}")

    def _validate_audio(self, filepath: Path, result: Dict[str, Any], file_type: str) -> None:
        """Validate audio file and update result"""
        try:
            if file_type == "audio/x-wav":
                with wave.open(str(filepath), "rb") as wav_file:
                    params = wav_file.getparams()
                    result["validation_details"].update(
                        {
                            "audio_channels": params.nchannels,
                            "audio_sample_width": params.sampwidth,
                            "audio_framerate": params.framerate,
                            "audio_frames": params.nframes,
                            "audio_duration": params.nframes / params.framerate,
                        }
                    )
            else:
                audio_file = mutagen.File(filepath)
                if audio_file:
                    result["validation_details"].update(
                        {
                            "audio_length": audio_file.info.length,
                            "audio_bitrate": getattr(audio_file.info, "bitrate", None),
                            "audio_metadata_tags": len(audio_file.keys()) if audio_file else 0,
                        }
                    )
        except (wave.Error, mutagen.MutagenError) as e:
            result["errors"].append(f"Invalid audio file: {str(e)}")
        except Exception as e:
            result["errors"].append(f"Error validating audio file: {str(e)}")

    def _validate_generic(self, filepath: Path, result: Dict[str, Any]) -> None:
        """Validate generic file readability and update result"""
        try:
            with open(filepath, "rb") as f:
                first_chunk = f.read(1024)
                result["validation_details"].update(
                    {
                        "first_bytes_readable": True,
                        "first_chunk_size": len(first_chunk),
                        "appears_binary": any(b < 32 and b not in [9, 10, 13] for b in first_chunk[:100]),
                    }
                )
        except Exception as e:
            result["errors"].append(f"Unable to read file: {str(e)}")

    def save_report(self, validation_result: Dict[str, Any], output_path: Path) -> None:
        """Save validation report to JSON file"""
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(validation_result, f, indent=2, ensure_ascii=False)
