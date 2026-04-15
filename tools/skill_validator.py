#!/usr/bin/env python3
"""
Skill Validator - Validates skill directories against quality standards

Unified validator with three modes:
  1. Structure validation (default) — checks file layout, frontmatter, scripts
  2. Quality scoring (--quality)    — multi-dimensional quality assessment with grades
  3. Orchestra validation (--orchestra) — validates department skills

Usage:
    python skill_validator.py <skill_path> [--tier TIER] [--json] [--verbose]
    python skill_validator.py <skill_path> --quality [--detailed] [--minimum-score 75]
    python skill_validator.py <skill_path> --orchestra
    python skill_validator.py --orchestra --all

Author: Claude Skills Engineering Team
Version: 2.0.0
Dependencies: Python Standard Library Only
"""

import argparse
import ast
import json
import os
import re
import sys
import glob as globmod
try:
    import yaml
except ImportError:
    # Minimal YAML subset: parse simple key: value frontmatter without pyyaml
    class _YamlStub:
        class YAMLError(Exception):
            pass
        @staticmethod
        def safe_load(text):
            result = {}
            for line in text.strip().splitlines():
                if ':' in line:
                    key, _, value = line.partition(':')
                    result[key.strip()] = value.strip()
            return result if result else None
    yaml = _YamlStub()
import datetime as dt
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

class ValidationError(Exception):
    """Custom exception for validation errors"""
    pass


# ---------------------------------------------------------------------------
# Mode 1: Structure Validation (default)
# ---------------------------------------------------------------------------

class ValidationReport:
    """Container for validation results"""

    def __init__(self, skill_path: str):
        self.skill_path = skill_path
        self.timestamp = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
        self.checks = {}
        self.warnings = []
        self.errors = []
        self.suggestions = []
        self.overall_score = 0.0
        self.compliance_level = "FAIL"

    def add_check(self, check_name: str, passed: bool, message: str = "", score: float = 0.0):
        """Add a validation check result"""
        self.checks[check_name] = {
            "passed": passed,
            "message": message,
            "score": score
        }

    def add_warning(self, message: str):
        """Add a warning message"""
        self.warnings.append(message)

    def add_error(self, message: str):
        """Add an error message"""
        self.errors.append(message)

    def add_suggestion(self, message: str):
        """Add an improvement suggestion"""
        self.suggestions.append(message)

    def calculate_overall_score(self):
        """Calculate overall compliance score"""
        if not self.checks:
            self.overall_score = 0.0
            return

        total_score = sum(check["score"] for check in self.checks.values())
        max_score = len(self.checks) * 1.0
        self.overall_score = (total_score / max_score) * 100 if max_score > 0 else 0.0

        # Determine compliance level
        if self.overall_score >= 90:
            self.compliance_level = "EXCELLENT"
        elif self.overall_score >= 75:
            self.compliance_level = "GOOD"
        elif self.overall_score >= 60:
            self.compliance_level = "ACCEPTABLE"
        elif self.overall_score >= 40:
            self.compliance_level = "NEEDS_IMPROVEMENT"
        else:
            self.compliance_level = "POOR"


class SkillValidator:
    """Main skill validation engine"""

    # Tier requirements
    TIER_REQUIREMENTS = {
        "BASIC": {
            "min_skill_md_lines": 100,
            "min_scripts": 1,
            "script_size_range": (100, 300),
            "required_dirs": ["scripts"],
            "optional_dirs": ["assets", "references", "expected_outputs"],
            "features_required": ["argparse", "main_guard"]
        },
        "STANDARD": {
            "min_skill_md_lines": 200,
            "min_scripts": 1,
            "script_size_range": (300, 500),
            "required_dirs": ["scripts", "assets", "references"],
            "optional_dirs": ["expected_outputs"],
            "features_required": ["argparse", "main_guard", "json_output", "help_text"]
        },
        "POWERFUL": {
            "min_skill_md_lines": 300,
            "min_scripts": 2,
            "script_size_range": (500, 800),
            "required_dirs": ["scripts", "assets", "references", "expected_outputs"],
            "optional_dirs": [],
            "features_required": ["argparse", "main_guard", "json_output", "help_text", "error_handling"]
        }
    }

    REQUIRED_SKILL_MD_SECTIONS = [
        "Name", "Description", "Features", "Usage", "Examples"
    ]

    FRONTMATTER_REQUIRED_FIELDS = [
        "Name", "Tier", "Category", "Dependencies", "Author", "Version"
    ]

    def __init__(self, skill_path: str, target_tier: Optional[str] = None, verbose: bool = False):
        self.skill_path = Path(skill_path).resolve()
        self.target_tier = target_tier
        self.verbose = verbose
        self.report = ValidationReport(str(self.skill_path))

    def log_verbose(self, message: str):
        """Log verbose message if verbose mode enabled"""
        if self.verbose:
            print(f"[VERBOSE] {message}", file=sys.stderr)

    def validate_skill_structure(self) -> ValidationReport:
        """Main validation entry point"""
        try:
            self.log_verbose(f"Starting validation of {self.skill_path}")

            # Check if path exists
            if not self.skill_path.exists():
                self.report.add_error(f"Skill path does not exist: {self.skill_path}")
                return self.report

            if not self.skill_path.is_dir():
                self.report.add_error(f"Skill path is not a directory: {self.skill_path}")
                return self.report

            # Run all validation checks
            self._validate_required_files()
            self._validate_skill_md()
            self._validate_readme()
            self._validate_directory_structure()
            self._validate_python_scripts()
            self._validate_tier_compliance()

            # Calculate overall score
            self.report.calculate_overall_score()

            self.log_verbose(f"Validation completed. Score: {self.report.overall_score:.1f}")

        except Exception as e:
            self.report.add_error(f"Validation failed with exception: {str(e)}")

        return self.report

    def _validate_required_files(self):
        """Validate presence of required files"""
        self.log_verbose("Checking required files...")

        # Check SKILL.md
        skill_md_path = self.skill_path / "SKILL.md"
        if skill_md_path.exists():
            self.report.add_check("skill_md_exists", True, "SKILL.md found", 1.0)
        else:
            self.report.add_check("skill_md_exists", False, "SKILL.md missing", 0.0)
            self.report.add_error("SKILL.md is required but missing")

        # Check README.md
        readme_path = self.skill_path / "README.md"
        if readme_path.exists():
            self.report.add_check("readme_exists", True, "README.md found", 1.0)
        else:
            self.report.add_check("readme_exists", False, "README.md missing", 0.0)
            self.report.add_warning("README.md is recommended but missing")
            self.report.add_suggestion("Add README.md with usage instructions and examples")

    def _validate_skill_md(self):
        """Validate SKILL.md content and format"""
        self.log_verbose("Validating SKILL.md...")

        skill_md_path = self.skill_path / "SKILL.md"
        if not skill_md_path.exists():
            return

        try:
            content = skill_md_path.read_text(encoding='utf-8')
            lines = content.split('\n')
            line_count = len([line for line in lines if line.strip()])

            # Check line count
            min_lines = self._get_tier_requirement("min_skill_md_lines", 100)
            if line_count >= min_lines:
                self.report.add_check("skill_md_length", True,
                                     f"SKILL.md has {line_count} lines (>={min_lines})", 1.0)
            else:
                self.report.add_check("skill_md_length", False,
                                     f"SKILL.md has {line_count} lines (<{min_lines})", 0.0)
                self.report.add_error(f"SKILL.md too short: {line_count} lines, minimum {min_lines}")

            # Validate frontmatter
            self._validate_frontmatter(content)

            # Check required sections
            self._validate_required_sections(content)

        except Exception as e:
            self.report.add_check("skill_md_readable", False, f"Error reading SKILL.md: {str(e)}", 0.0)
            self.report.add_error(f"Cannot read SKILL.md: {str(e)}")

    def _validate_frontmatter(self, content: str):
        """Validate SKILL.md frontmatter"""
        self.log_verbose("Validating frontmatter...")

        # Extract frontmatter
        if content.startswith('---'):
            try:
                end_marker = content.find('---', 3)
                if end_marker == -1:
                    self.report.add_check("frontmatter_format", False,
                                         "Frontmatter closing marker not found", 0.0)
                    return

                frontmatter_text = content[3:end_marker].strip()
                frontmatter = yaml.safe_load(frontmatter_text)

                if not isinstance(frontmatter, dict):
                    self.report.add_check("frontmatter_format", False,
                                         "Frontmatter is not a valid dictionary", 0.0)
                    return

                # Check required fields
                missing_fields = []
                for field in self.FRONTMATTER_REQUIRED_FIELDS:
                    if field not in frontmatter:
                        missing_fields.append(field)

                if not missing_fields:
                    self.report.add_check("frontmatter_complete", True,
                                         "All required frontmatter fields present", 1.0)
                else:
                    self.report.add_check("frontmatter_complete", False,
                                         f"Missing fields: {', '.join(missing_fields)}", 0.0)
                    self.report.add_error(f"Missing frontmatter fields: {', '.join(missing_fields)}")

            except yaml.YAMLError as e:
                self.report.add_check("frontmatter_format", False,
                                     f"Invalid YAML frontmatter: {str(e)}", 0.0)
                self.report.add_error(f"Invalid YAML frontmatter: {str(e)}")

        else:
            self.report.add_check("frontmatter_exists", False,
                                 "No frontmatter found", 0.0)
            self.report.add_error("SKILL.md must start with YAML frontmatter")

    def _validate_required_sections(self, content: str):
        """Validate required sections in SKILL.md"""
        self.log_verbose("Checking required sections...")

        missing_sections = []
        for section in self.REQUIRED_SKILL_MD_SECTIONS:
            pattern = rf'^#+\s*{re.escape(section)}\s*$'
            if not re.search(pattern, content, re.MULTILINE | re.IGNORECASE):
                missing_sections.append(section)

        if not missing_sections:
            self.report.add_check("required_sections", True,
                                 "All required sections present", 1.0)
        else:
            self.report.add_check("required_sections", False,
                                 f"Missing sections: {', '.join(missing_sections)}", 0.0)
            self.report.add_error(f"Missing required sections: {', '.join(missing_sections)}")

    def _validate_readme(self):
        """Validate README.md content"""
        self.log_verbose("Validating README.md...")

        readme_path = self.skill_path / "README.md"
        if not readme_path.exists():
            return

        try:
            content = readme_path.read_text(encoding='utf-8')

            # Check minimum content length
            if len(content.strip()) >= 200:
                self.report.add_check("readme_substantial", True,
                                     "README.md has substantial content", 1.0)
            else:
                self.report.add_check("readme_substantial", False,
                                     "README.md content is too brief", 0.5)
                self.report.add_suggestion("Expand README.md with more detailed usage instructions")

        except Exception as e:
            self.report.add_check("readme_readable", False,
                                 f"Error reading README.md: {str(e)}", 0.0)

    def _validate_directory_structure(self):
        """Validate directory structure against tier requirements"""
        self.log_verbose("Validating directory structure...")

        required_dirs = self._get_tier_requirement("required_dirs", ["scripts"])
        optional_dirs = self._get_tier_requirement("optional_dirs", [])

        # Check required directories
        missing_required = []
        for dir_name in required_dirs:
            dir_path = self.skill_path / dir_name
            if dir_path.exists() and dir_path.is_dir():
                self.report.add_check(f"dir_{dir_name}_exists", True,
                                     f"{dir_name}/ directory found", 1.0)
            else:
                missing_required.append(dir_name)
                self.report.add_check(f"dir_{dir_name}_exists", False,
                                     f"{dir_name}/ directory missing", 0.0)

        if missing_required:
            self.report.add_error(f"Missing required directories: {', '.join(missing_required)}")

        # Check optional directories and provide suggestions
        missing_optional = []
        for dir_name in optional_dirs:
            dir_path = self.skill_path / dir_name
            if not (dir_path.exists() and dir_path.is_dir()):
                missing_optional.append(dir_name)

        if missing_optional:
            self.report.add_suggestion(f"Consider adding optional directories: {', '.join(missing_optional)}")

    def _validate_python_scripts(self):
        """Validate Python scripts in the scripts directory"""
        self.log_verbose("Validating Python scripts...")

        scripts_dir = self.skill_path / "scripts"
        if not scripts_dir.exists():
            return

        python_files = list(scripts_dir.glob("*.py"))
        min_scripts = self._get_tier_requirement("min_scripts", 1)

        # Check minimum number of scripts
        if len(python_files) >= min_scripts:
            self.report.add_check("min_scripts_count", True,
                                 f"Found {len(python_files)} Python scripts (>={min_scripts})", 1.0)
        else:
            self.report.add_check("min_scripts_count", False,
                                 f"Found {len(python_files)} Python scripts (<{min_scripts})", 0.0)
            self.report.add_error(f"Insufficient scripts: {len(python_files)}, minimum {min_scripts}")

        # Validate each script
        for script_path in python_files:
            self._validate_single_script(script_path)

    def _validate_single_script(self, script_path: Path):
        """Validate a single Python script"""
        script_name = script_path.name
        self.log_verbose(f"Validating script: {script_name}")

        try:
            content = script_path.read_text(encoding='utf-8')

            # Count lines of code (excluding empty lines and comments)
            lines = content.split('\n')
            loc = len([line for line in lines if line.strip() and not line.strip().startswith('#')])

            # Check script size against tier requirements
            size_range = self._get_tier_requirement("script_size_range", (100, 1000))
            min_size, max_size = size_range

            if min_size <= loc <= max_size:
                self.report.add_check(f"script_size_{script_name}", True,
                                     f"{script_name} has {loc} LOC (within {min_size}-{max_size})", 1.0)
            else:
                self.report.add_check(f"script_size_{script_name}", False,
                                     f"{script_name} has {loc} LOC (outside {min_size}-{max_size})", 0.5)
                if loc < min_size:
                    self.report.add_suggestion(f"Consider expanding {script_name} (currently {loc} LOC)")
                else:
                    self.report.add_suggestion(f"Consider refactoring {script_name} (currently {loc} LOC)")

            # Parse and validate Python syntax
            try:
                tree = ast.parse(content)
                self.report.add_check(f"script_syntax_{script_name}", True,
                                     f"{script_name} has valid Python syntax", 1.0)

                # Check for required features
                self._validate_script_features(tree, script_name, content)

            except SyntaxError as e:
                self.report.add_check(f"script_syntax_{script_name}", False,
                                     f"{script_name} has syntax error: {str(e)}", 0.0)
                self.report.add_error(f"Syntax error in {script_name}: {str(e)}")

        except Exception as e:
            self.report.add_check(f"script_readable_{script_name}", False,
                                 f"Cannot read {script_name}: {str(e)}", 0.0)
            self.report.add_error(f"Cannot read {script_name}: {str(e)}")

    def _validate_script_features(self, tree: ast.AST, script_name: str, content: str):
        """Validate required script features"""
        required_features = self._get_tier_requirement("features_required", ["argparse", "main_guard"])

        # Check for argparse usage
        if "argparse" in required_features:
            has_argparse = self._check_argparse_usage(tree)
            self.report.add_check(f"script_argparse_{script_name}", has_argparse,
                                 f"{'Uses' if has_argparse else 'Missing'} argparse in {script_name}", 1.0 if has_argparse else 0.0)
            if not has_argparse:
                self.report.add_error(f"{script_name} must use argparse for command-line arguments")

        # Check for main guard
        if "main_guard" in required_features:
            has_main_guard = 'if __name__ == "__main__"' in content
            self.report.add_check(f"script_main_guard_{script_name}", has_main_guard,
                                 f"{'Has' if has_main_guard else 'Missing'} main guard in {script_name}", 1.0 if has_main_guard else 0.0)
            if not has_main_guard:
                self.report.add_error(f"{script_name} must have 'if __name__ == \"__main__\"' guard")

        # Check for external imports (should only use stdlib)
        external_imports = self._check_external_imports(tree)
        if not external_imports:
            self.report.add_check(f"script_imports_{script_name}", True,
                                 f"{script_name} uses only standard library", 1.0)
        else:
            self.report.add_check(f"script_imports_{script_name}", False,
                                 f"{script_name} uses external imports: {', '.join(external_imports)}", 0.0)
            self.report.add_error(f"{script_name} uses external imports: {', '.join(external_imports)}")

    def _check_argparse_usage(self, tree: ast.AST) -> bool:
        """Check if the script uses argparse"""
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == 'argparse':
                        return True
            elif isinstance(node, ast.ImportFrom):
                if node.module == 'argparse':
                    return True
        return False

    def _check_external_imports(self, tree: ast.AST) -> List[str]:
        """Check for external (non-stdlib) imports"""
        stdlib_modules = {
            'argparse', 'ast', 'json', 'os', 'sys', 'pathlib', 'datetime', 'typing',
            'collections', 're', 'math', 'random', 'itertools', 'functools', 'operator',
            'csv', 'sqlite3', 'urllib', 'http', 'html', 'xml', 'email', 'base64',
            'hashlib', 'hmac', 'secrets', 'tempfile', 'shutil', 'glob', 'fnmatch',
            'subprocess', 'threading', 'multiprocessing', 'queue', 'time', 'calendar',
            'zoneinfo', 'locale', 'gettext', 'logging', 'warnings', 'unittest',
            'doctest', 'pickle', 'copy', 'pprint', 'reprlib', 'enum', 'dataclasses',
            'contextlib', 'abc', 'atexit', 'traceback', 'gc', 'weakref', 'types',
            'copy', 'pprint', 'reprlib', 'enum', 'decimal', 'fractions', 'statistics',
            'cmath', 'platform', 'errno', 'io', 'codecs', 'unicodedata', 'stringprep',
            'textwrap', 'string', 'struct', 'difflib', 'heapq', 'bisect', 'array',
            'weakref', 'types', 'copyreg', 'uuid', 'mmap', 'ctypes'
        }

        external_imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module_name = alias.name.split('.')[0]
                    if module_name not in stdlib_modules:
                        external_imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                module_name = node.module.split('.')[0]
                if module_name not in stdlib_modules:
                    external_imports.append(node.module)

        return list(set(external_imports))

    def _validate_tier_compliance(self):
        """Validate overall tier compliance"""
        if not self.target_tier:
            return

        self.log_verbose(f"Validating {self.target_tier} tier compliance...")

        critical_checks = ["skill_md_exists", "min_scripts_count", "skill_md_length"]
        failed_critical = [check for check in critical_checks
                          if check in self.report.checks and not self.report.checks[check]["passed"]]

        if not failed_critical:
            self.report.add_check("tier_compliance", True,
                                 f"Meets {self.target_tier} tier requirements", 1.0)
        else:
            self.report.add_check("tier_compliance", False,
                                 f"Does not meet {self.target_tier} tier requirements", 0.0)
            self.report.add_error(f"Failed critical checks for {self.target_tier} tier: {', '.join(failed_critical)}")

    def _get_tier_requirement(self, requirement: str, default: Any) -> Any:
        """Get tier-specific requirement value"""
        if self.target_tier and self.target_tier in self.TIER_REQUIREMENTS:
            return self.TIER_REQUIREMENTS[self.target_tier].get(requirement, default)
        return default


class ReportFormatter:
    """Formats validation reports for output"""

    @staticmethod
    def format_json(report: ValidationReport) -> str:
        """Format report as JSON"""
        return json.dumps({
            "skill_path": report.skill_path,
            "timestamp": report.timestamp,
            "overall_score": round(report.overall_score, 1),
            "compliance_level": report.compliance_level,
            "checks": report.checks,
            "warnings": report.warnings,
            "errors": report.errors,
            "suggestions": report.suggestions
        }, indent=2)

    @staticmethod
    def format_human_readable(report: ValidationReport) -> str:
        """Format report as human-readable text"""
        lines = []
        lines.append("=" * 60)
        lines.append("SKILL VALIDATION REPORT")
        lines.append("=" * 60)
        lines.append(f"Skill: {report.skill_path}")
        lines.append(f"Timestamp: {report.timestamp}")
        lines.append(f"Overall Score: {report.overall_score:.1f}/100 ({report.compliance_level})")
        lines.append("")

        # Group checks by category
        structure_checks = {k: v for k, v in report.checks.items() if k.startswith(('skill_md', 'readme', 'dir_'))}
        script_checks = {k: v for k, v in report.checks.items() if k.startswith('script_')}
        other_checks = {k: v for k, v in report.checks.items() if k not in structure_checks and k not in script_checks}

        if structure_checks:
            lines.append("STRUCTURE VALIDATION:")
            for check_name, result in structure_checks.items():
                status = "PASS" if result["passed"] else "FAIL"
                lines.append(f"  {status}: {result['message']}")
            lines.append("")

        if script_checks:
            lines.append("SCRIPT VALIDATION:")
            for check_name, result in script_checks.items():
                status = "PASS" if result["passed"] else "FAIL"
                lines.append(f"  {status}: {result['message']}")
            lines.append("")

        if other_checks:
            lines.append("OTHER CHECKS:")
            for check_name, result in other_checks.items():
                status = "PASS" if result["passed"] else "FAIL"
                lines.append(f"  {status}: {result['message']}")
            lines.append("")

        if report.errors:
            lines.append("ERRORS:")
            for error in report.errors:
                lines.append(f"  - {error}")
            lines.append("")

        if report.warnings:
            lines.append("WARNINGS:")
            for warning in report.warnings:
                lines.append(f"  - {warning}")
            lines.append("")

        if report.suggestions:
            lines.append("SUGGESTIONS:")
            for suggestion in report.suggestions:
                lines.append(f"  - {suggestion}")
            lines.append("")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Mode 2: Quality Scoring (--quality)
# ---------------------------------------------------------------------------

class QualityDimension:
    """Represents a quality scoring dimension"""

    def __init__(self, name: str, weight: float, description: str):
        self.name = name
        self.weight = weight
        self.description = description
        self.score = 0.0
        self.max_score = 100.0
        self.details = {}
        self.suggestions = []

    def add_score(self, component: str, score: float, max_score: float, details: str = ""):
        """Add a component score"""
        self.details[component] = {
            "score": score,
            "max_score": max_score,
            "percentage": (score / max_score * 100) if max_score > 0 else 0,
            "details": details
        }

    def calculate_final_score(self):
        """Calculate the final weighted score for this dimension"""
        if not self.details:
            self.score = 0.0
            return

        total_score = sum(detail["score"] for detail in self.details.values())
        total_max = sum(detail["max_score"] for detail in self.details.values())

        self.score = (total_score / total_max * 100) if total_max > 0 else 0.0

    def add_suggestion(self, suggestion: str):
        """Add an improvement suggestion"""
        self.suggestions.append(suggestion)


class QualityReport:
    """Container for quality assessment results"""

    def __init__(self, skill_path: str):
        self.skill_path = skill_path
        self.timestamp = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
        self.dimensions = {}
        self.overall_score = 0.0
        self.letter_grade = "F"
        self.tier_recommendation = "BASIC"
        self.improvement_roadmap = []
        self.summary_stats = {}

    def add_dimension(self, dimension: QualityDimension):
        """Add a quality dimension"""
        self.dimensions[dimension.name] = dimension

    def calculate_overall_score(self):
        """Calculate overall weighted score"""
        if not self.dimensions:
            return

        total_weighted_score = 0.0
        total_weight = 0.0

        for dimension in self.dimensions.values():
            total_weighted_score += dimension.score * dimension.weight
            total_weight += dimension.weight

        self.overall_score = total_weighted_score / total_weight if total_weight > 0 else 0.0

        # Calculate letter grade
        if self.overall_score >= 95:
            self.letter_grade = "A+"
        elif self.overall_score >= 90:
            self.letter_grade = "A"
        elif self.overall_score >= 85:
            self.letter_grade = "A-"
        elif self.overall_score >= 80:
            self.letter_grade = "B+"
        elif self.overall_score >= 75:
            self.letter_grade = "B"
        elif self.overall_score >= 70:
            self.letter_grade = "B-"
        elif self.overall_score >= 65:
            self.letter_grade = "C+"
        elif self.overall_score >= 60:
            self.letter_grade = "C"
        elif self.overall_score >= 55:
            self.letter_grade = "C-"
        elif self.overall_score >= 50:
            self.letter_grade = "D"
        else:
            self.letter_grade = "F"

        self._calculate_tier_recommendation()
        self._generate_improvement_roadmap()
        self._calculate_summary_stats()

    def _calculate_tier_recommendation(self):
        """Calculate recommended tier based on quality scores"""
        doc_score = self.dimensions.get("Documentation", QualityDimension("", 0, "")).score
        code_score = self.dimensions.get("Code Quality", QualityDimension("", 0, "")).score
        completeness_score = self.dimensions.get("Completeness", QualityDimension("", 0, "")).score
        usability_score = self.dimensions.get("Usability", QualityDimension("", 0, "")).score

        if (self.overall_score >= 80 and
            all(score >= 75 for score in [doc_score, code_score, completeness_score, usability_score])):
            self.tier_recommendation = "POWERFUL"
        elif (self.overall_score >= 70 and
              sum(1 for score in [doc_score, code_score, completeness_score, usability_score] if score >= 65) >= 3):
            self.tier_recommendation = "STANDARD"
        else:
            self.tier_recommendation = "BASIC"

    def _generate_improvement_roadmap(self):
        """Generate prioritized improvement suggestions"""
        all_suggestions = []

        for dim_name, dimension in self.dimensions.items():
            for suggestion in dimension.suggestions:
                priority = "HIGH" if dimension.score < 60 else "MEDIUM" if dimension.score < 75 else "LOW"
                all_suggestions.append({
                    "priority": priority,
                    "dimension": dim_name,
                    "suggestion": suggestion,
                    "current_score": dimension.score
                })

        priority_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        all_suggestions.sort(key=lambda x: (priority_order[x["priority"]], x["current_score"]))

        self.improvement_roadmap = all_suggestions[:10]

    def _calculate_summary_stats(self):
        """Calculate summary statistics"""
        scores = [dim.score for dim in self.dimensions.values()]

        self.summary_stats = {
            "highest_dimension": max(self.dimensions.items(), key=lambda x: x[1].score)[0] if scores else "None",
            "lowest_dimension": min(self.dimensions.items(), key=lambda x: x[1].score)[0] if scores else "None",
            "score_variance": sum((score - self.overall_score) ** 2 for score in scores) / len(scores) if scores else 0,
            "dimensions_above_70": sum(1 for score in scores if score >= 70),
            "dimensions_below_50": sum(1 for score in scores if score < 50)
        }


class QualityScorer:
    """Multi-dimensional quality scoring engine"""

    def __init__(self, skill_path: str, detailed: bool = False, verbose: bool = False):
        self.skill_path = Path(skill_path).resolve()
        self.detailed = detailed
        self.verbose = verbose
        self.report = QualityReport(str(self.skill_path))

    def log_verbose(self, message: str):
        if self.verbose:
            print(f"[VERBOSE] {message}", file=sys.stderr)

    def assess_quality(self) -> QualityReport:
        """Main quality assessment entry point"""
        try:
            self.log_verbose(f"Starting quality assessment for {self.skill_path}")

            if not self.skill_path.exists():
                raise ValueError(f"Skill path does not exist: {self.skill_path}")

            self._score_documentation()
            self._score_code_quality()
            self._score_completeness()
            self._score_usability()

            self.report.calculate_overall_score()

            self.log_verbose(f"Quality assessment completed. Overall score: {self.report.overall_score:.1f}")

        except Exception as e:
            print(f"Quality assessment failed: {str(e)}", file=sys.stderr)
            raise

        return self.report

    def _score_documentation(self):
        """Score documentation quality (25% weight)"""
        self.log_verbose("Scoring documentation quality...")

        dimension = QualityDimension("Documentation", 0.25, "Quality of documentation and written materials")

        skill_md_path = self.skill_path / "SKILL.md"
        if skill_md_path.exists():
            try:
                content = skill_md_path.read_text(encoding='utf-8')
                lines = [line for line in content.split('\n') if line.strip()]
                line_count = len(lines)

                # Length score
                if line_count >= 400:
                    length_score = 25
                elif line_count >= 300:
                    length_score = 20
                elif line_count >= 200:
                    length_score = 15
                elif line_count >= 100:
                    length_score = 10
                else:
                    length_score = 5

                dimension.add_score("skill_md_length", length_score, 25,
                                   f"SKILL.md has {line_count} lines")
                if line_count < 300:
                    dimension.add_suggestion("Expand SKILL.md with more detailed sections")

                # Frontmatter score
                frontmatter_score = self._score_frontmatter(content)
                dimension.add_score("skill_md_frontmatter", frontmatter_score, 25,
                                   "Frontmatter completeness and accuracy")

                # Section score
                section_score = self._score_sections(content)
                dimension.add_score("skill_md_sections", section_score, 25,
                                   "Required and recommended section coverage")

                # Content depth
                depth_score = self._score_content_depth(content)
                dimension.add_score("skill_md_depth", depth_score, 25,
                                   "Content depth and technical detail")

            except Exception as e:
                dimension.add_score("skill_md_readable", 0, 25, f"Error reading SKILL.md: {str(e)}")
                dimension.add_suggestion("Fix SKILL.md file encoding or format issues")
        else:
            dimension.add_score("skill_md_existence", 0, 25, "SKILL.md does not exist")
            dimension.add_suggestion("Create comprehensive SKILL.md file")

        # README score
        readme_path = self.skill_path / "README.md"
        if readme_path.exists():
            try:
                content = readme_path.read_text(encoding='utf-8')
                if len(content.strip()) >= 1000:
                    length_score = 25
                elif len(content.strip()) >= 500:
                    length_score = 20
                elif len(content.strip()) >= 200:
                    length_score = 15
                else:
                    length_score = 10
                dimension.add_score("readme_quality", length_score, 25,
                                   f"README.md content quality ({len(content)} characters)")
                if len(content.strip()) < 500:
                    dimension.add_suggestion("Expand README.md with more detailed usage examples")
            except Exception:
                dimension.add_score("readme_readable", 5, 25, "README.md exists but has issues")
        else:
            dimension.add_score("readme_existence", 10, 25, "README.md exists (partial credit)")
            dimension.add_suggestion("Create README.md with usage instructions")

        dimension.calculate_final_score()
        self.report.add_dimension(dimension)

    def _score_frontmatter(self, content: str) -> float:
        """Score SKILL.md frontmatter quality"""
        required_fields = ["Name", "Tier", "Category", "Dependencies", "Author", "Version"]
        recommended_fields = ["Last Updated", "Description"]

        try:
            if not content.startswith('---'):
                return 5
            end_marker = content.find('---', 3)
            if end_marker == -1:
                return 5
            frontmatter_text = content[3:end_marker].strip()
            frontmatter = yaml.safe_load(frontmatter_text)
            if not isinstance(frontmatter, dict):
                return 5

            score = 0
            present_required = sum(1 for field in required_fields if field in frontmatter)
            score += (present_required / len(required_fields)) * 15
            present_recommended = sum(1 for field in recommended_fields if field in frontmatter)
            score += (present_recommended / len(recommended_fields)) * 5
            quality_bonus = 0
            for field, value in frontmatter.items():
                if isinstance(value, str) and len(value.strip()) > 3:
                    quality_bonus += 0.5
            score += min(quality_bonus, 5)
            return min(score, 25)
        except yaml.YAMLError:
            return 5

    def _score_sections(self, content: str) -> float:
        """Score section completeness"""
        required_sections = ["Description", "Features", "Usage", "Examples"]
        recommended_sections = ["Architecture", "Installation", "Troubleshooting", "Contributing"]

        score = 0
        present_required = 0
        for section in required_sections:
            if re.search(rf'^#+\s*{re.escape(section)}\s*$', content, re.MULTILINE | re.IGNORECASE):
                present_required += 1
        score += (present_required / len(required_sections)) * 15

        present_recommended = 0
        for section in recommended_sections:
            if re.search(rf'^#+\s*{re.escape(section)}\s*$', content, re.MULTILINE | re.IGNORECASE):
                present_recommended += 1
        score += (present_recommended / len(recommended_sections)) * 10

        return score

    def _score_content_depth(self, content: str) -> float:
        """Score content depth and technical detail"""
        score = 0

        code_blocks = len(re.findall(r'```[\w]*\n.*?\n```', content, re.DOTALL))
        score += min(code_blocks * 2, 8)

        depth_indicators = ['API', 'algorithm', 'architecture', 'implementation', 'performance',
                           'scalability', 'security', 'integration', 'configuration', 'parameters']
        depth_score = sum(1 for indicator in depth_indicators if indicator.lower() in content.lower())
        score += min(depth_score * 0.8, 8)

        example_patterns = [r'Example:', r'Usage:', r'```bash', r'```python', r'```yaml']
        example_count = sum(len(re.findall(pattern, content, re.IGNORECASE)) for pattern in example_patterns)
        score += min(example_count * 1.5, 9)

        return score

    def _score_code_quality(self):
        """Score code quality (25% weight)"""
        self.log_verbose("Scoring code quality...")

        dimension = QualityDimension("Code Quality", 0.25, "Quality of Python scripts and implementation")

        scripts_dir = self.skill_path / "scripts"
        if not scripts_dir.exists():
            dimension.add_score("scripts_existence", 0, 100, "No scripts directory")
            dimension.add_suggestion("Create scripts directory with Python files")
            dimension.calculate_final_score()
            self.report.add_dimension(dimension)
            return

        python_files = list(scripts_dir.glob("*.py"))
        if not python_files:
            dimension.add_score("python_scripts", 0, 100, "No Python scripts found")
            dimension.add_suggestion("Add Python scripts to scripts directory")
            dimension.calculate_final_score()
            self.report.add_dimension(dimension)
            return

        # Complexity
        total_complexity = 0
        script_count = len(python_files)
        for script_path in python_files:
            try:
                content = script_path.read_text(encoding='utf-8')
                lines = content.split('\n')
                loc = len([line for line in lines if line.strip() and not line.strip().startswith('#')])
                if loc >= 800:
                    total_complexity += 25
                elif loc >= 500:
                    total_complexity += 20
                elif loc >= 300:
                    total_complexity += 15
                elif loc >= 100:
                    total_complexity += 10
                else:
                    total_complexity += 5
            except Exception:
                continue
        avg_complexity = total_complexity / script_count if script_count > 0 else 0
        dimension.add_score("script_complexity", avg_complexity, 25,
                           f"Average script complexity across {script_count} scripts")
        if avg_complexity < 15:
            dimension.add_suggestion("Consider expanding scripts with more functionality")

        # Error handling
        total_error_score = 0
        for script_path in python_files:
            try:
                content = script_path.read_text(encoding='utf-8')
                error_score = 0
                try_count = content.count('try:')
                error_score += min(try_count * 5, 15)
                exception_types = ['Exception', 'ValueError', 'FileNotFoundError', 'KeyError', 'TypeError']
                for exc_type in exception_types:
                    if exc_type in content:
                        error_score += 2
                if any(indicator in content for indicator in ['print(', 'logging.', 'sys.stderr']):
                    error_score += 5
                total_error_score += min(error_score, 25)
            except Exception:
                continue
        avg_error_score = total_error_score / script_count if script_count > 0 else 0
        dimension.add_score("error_handling", avg_error_score, 25,
                           f"Error handling quality across {script_count} scripts")
        if avg_error_score < 15:
            dimension.add_suggestion("Improve error handling with try/except blocks and meaningful error messages")

        # Code structure
        total_structure_score = 0
        for script_path in python_files:
            try:
                content = script_path.read_text(encoding='utf-8')
                structure_score = 0
                function_count = content.count('def ')
                class_count = content.count('class ')
                structure_score += min(function_count * 2, 10)
                structure_score += min(class_count * 3, 9)
                docstring_patterns = ['"""', "'''", 'def.*:\n.*"""', 'class.*:\n.*"""']
                for pattern in docstring_patterns:
                    if re.search(pattern, content):
                        structure_score += 1
                if 'if __name__ == "__main__"' in content:
                    structure_score += 3
                if content.lstrip().startswith(('import ', 'from ')):
                    structure_score += 2
                total_structure_score += min(structure_score, 25)
            except Exception:
                continue
        avg_structure_score = total_structure_score / script_count if script_count > 0 else 0
        dimension.add_score("code_structure", avg_structure_score, 25,
                           f"Code structure quality across {script_count} scripts")
        if avg_structure_score < 15:
            dimension.add_suggestion("Improve code structure with more functions, classes, and documentation")

        # Output support
        total_output_score = 0
        for script_path in python_files:
            try:
                content = script_path.read_text(encoding='utf-8')
                output_score = 0
                if any(indicator in content for indicator in ['json.dump', 'json.load', '--json']):
                    output_score += 12
                if any(indicator in content for indicator in ['print(f"', 'print("', '.format(', 'f"']):
                    output_score += 8
                if '--help' in content or 'add_help=' in content:
                    output_score += 5
                total_output_score += min(output_score, 25)
            except Exception:
                continue
        avg_output_score = total_output_score / script_count if script_count > 0 else 0
        dimension.add_score("output_support", avg_output_score, 25,
                           f"Output format support across {script_count} scripts")
        if avg_output_score < 15:
            dimension.add_suggestion("Add support for both JSON and human-readable output formats")

        dimension.calculate_final_score()
        self.report.add_dimension(dimension)

    def _score_completeness(self):
        """Score completeness (25% weight)"""
        self.log_verbose("Scoring completeness...")

        dimension = QualityDimension("Completeness", 0.25, "Completeness of required components and assets")

        # Directory structure
        required_dirs = ["scripts"]
        recommended_dirs = ["assets", "references", "expected_outputs"]
        score = 0
        for dir_name in required_dirs:
            if (self.skill_path / dir_name).exists():
                score += 15 / len(required_dirs)
        present_recommended = sum(1 for d in recommended_dirs if (self.skill_path / d).exists())
        score += (present_recommended / len(recommended_dirs)) * 10
        dimension.add_score("directory_structure", score, 25, "Directory structure completeness")
        missing_recommended = [d for d in recommended_dirs if not (self.skill_path / d).exists()]
        if missing_recommended:
            dimension.add_suggestion(f"Add recommended directories: {', '.join(missing_recommended)}")

        # Assets
        assets_dir = self.skill_path / "assets"
        if assets_dir.exists():
            asset_files = [f for f in assets_dir.rglob("*") if f.is_file()]
            if asset_files:
                asset_score = min(len(asset_files) * 3, 20)
                extensions = set(f.suffix.lower() for f in asset_files if f.suffix)
                if len(extensions) >= 3:
                    asset_score += 5
                dimension.add_score("assets_quality", asset_score, 25,
                                   f"Assets: {len(asset_files)} files, {len(extensions)} types")
            else:
                dimension.add_score("assets_content", 10, 25, "Assets directory empty")
                dimension.add_suggestion("Add sample data files to assets directory")
        else:
            dimension.add_score("assets_existence", 5, 25, "Assets directory missing")
            dimension.add_suggestion("Create assets directory with sample data")

        # Expected outputs
        expected_dir = self.skill_path / "expected_outputs"
        if expected_dir.exists():
            output_files = [f for f in expected_dir.rglob("*") if f.is_file()]
            if len(output_files) >= 3:
                eo_score = 25
            elif len(output_files) >= 2:
                eo_score = 20
            elif len(output_files) >= 1:
                eo_score = 15
            else:
                eo_score = 10
                dimension.add_suggestion("Add expected output files for testing")
            dimension.add_score("expected_outputs", eo_score, 25,
                               f"Expected outputs: {len(output_files)} files")
        else:
            dimension.add_score("expected_outputs", 10, 25, "Expected outputs directory missing")
            dimension.add_suggestion("Add expected_outputs directory with sample results")

        # Test coverage
        test_indicators = ["test", "spec", "check"]
        test_files = []
        for indicator in test_indicators:
            test_files.extend(self.skill_path.rglob(f"*{indicator}*"))
        test_score = 15
        if test_files:
            test_score += 10
        dimension.add_score("test_coverage", test_score, 25,
                           f"Test coverage indicators: {len(test_files)} files")
        if not test_files:
            dimension.add_suggestion("Add test files or validation scripts")

        dimension.calculate_final_score()
        self.report.add_dimension(dimension)

    def _score_usability(self):
        """Score usability (25% weight)"""
        self.log_verbose("Scoring usability...")

        dimension = QualityDimension("Usability", 0.25, "Ease of use and user experience")

        # Installation simplicity
        inst_score = 25
        if (self.skill_path / "requirements.txt").exists():
            inst_score -= 5
            dimension.add_suggestion("Consider removing external dependencies for easier installation")
        if (self.skill_path / "setup.py").exists():
            inst_score -= 3
        dimension.add_score("installation_simplicity", max(inst_score, 15), 25,
                           "Installation complexity assessment")

        # Usage clarity
        usage_score = 0
        readme_path = self.skill_path / "README.md"
        if readme_path.exists():
            try:
                content = readme_path.read_text(encoding='utf-8').lower()
                if 'usage' in content or 'how to' in content:
                    usage_score += 10
                if 'example' in content:
                    usage_score += 5
            except Exception:
                pass
        scripts_dir = self.skill_path / "scripts"
        if scripts_dir.exists():
            python_files = list(scripts_dir.glob("*.py"))
            help_quality = 0
            for script_path in python_files:
                try:
                    content = script_path.read_text(encoding='utf-8')
                    if 'argparse' in content and 'help=' in content:
                        help_quality += 2
                except Exception:
                    continue
            usage_score += min(help_quality, 10)
        dimension.add_score("usage_clarity", usage_score, 25, "Usage instructions and help quality")
        if usage_score < 15:
            dimension.add_suggestion("Improve usage documentation and help text")

        # Help accessibility
        help_score = 0
        if scripts_dir and scripts_dir.exists():
            python_files = list(scripts_dir.glob("*.py"))
            for script_path in python_files:
                try:
                    content = script_path.read_text(encoding='utf-8')
                    if 'epilog=' in content or 'description=' in content:
                        help_score += 5
                    if 'examples:' in content.lower() or 'example:' in content.lower():
                        help_score += 3
                except Exception:
                    continue
        doc_files = list(self.skill_path.glob("*.md"))
        if len(doc_files) >= 2:
            help_score += 5
        dimension.add_score("help_accessibility", min(help_score, 25), 25,
                           "Help and documentation accessibility")
        if help_score < 15:
            dimension.add_suggestion("Add more comprehensive help text and documentation")

        # Practical examples
        example_patterns = ["*example*", "*sample*", "*demo*", "*tutorial*"]
        example_files = []
        for pattern in example_patterns:
            example_files.extend(self.skill_path.rglob(pattern))
        if len(example_files) >= 5:
            ex_score = 25
        elif len(example_files) >= 3:
            ex_score = 20
        elif len(example_files) >= 2:
            ex_score = 15
        elif len(example_files) >= 1:
            ex_score = 10
        else:
            ex_score = 5
            dimension.add_suggestion("Add more practical examples and sample files")
        dimension.add_score("practical_examples", ex_score, 25,
                           f"Practical examples: {len(example_files)} files")

        dimension.calculate_final_score()
        self.report.add_dimension(dimension)


class QualityReportFormatter:
    """Formats quality reports for output"""

    @staticmethod
    def format_json(report: QualityReport) -> str:
        """Format report as JSON"""
        return json.dumps({
            "skill_path": report.skill_path,
            "timestamp": report.timestamp,
            "overall_score": round(report.overall_score, 1),
            "letter_grade": report.letter_grade,
            "tier_recommendation": report.tier_recommendation,
            "summary_stats": report.summary_stats,
            "dimensions": {
                name: {
                    "name": dim.name,
                    "weight": dim.weight,
                    "score": round(dim.score, 1),
                    "description": dim.description,
                    "details": dim.details,
                    "suggestions": dim.suggestions
                }
                for name, dim in report.dimensions.items()
            },
            "improvement_roadmap": report.improvement_roadmap
        }, indent=2)

    @staticmethod
    def format_human_readable(report: QualityReport, detailed: bool = False) -> str:
        """Format report as human-readable text"""
        lines = []
        lines.append("=" * 70)
        lines.append("SKILL QUALITY ASSESSMENT REPORT")
        lines.append("=" * 70)
        lines.append(f"Skill: {report.skill_path}")
        lines.append(f"Timestamp: {report.timestamp}")
        lines.append(f"Overall Score: {report.overall_score:.1f}/100 ({report.letter_grade})")
        lines.append(f"Recommended Tier: {report.tier_recommendation}")
        lines.append("")

        lines.append("QUALITY DIMENSIONS:")
        for name, dimension in report.dimensions.items():
            lines.append(f"  {name}: {dimension.score:.1f}/100 ({dimension.weight * 100:.0f}% weight)")
            if detailed and dimension.details:
                for component, details in dimension.details.items():
                    lines.append(f"    - {component}: {details['score']:.1f}/{details['max_score']} - {details['details']}")
            lines.append("")

        if report.summary_stats:
            lines.append("SUMMARY STATISTICS:")
            lines.append(f"  Highest Dimension: {report.summary_stats['highest_dimension']}")
            lines.append(f"  Lowest Dimension: {report.summary_stats['lowest_dimension']}")
            lines.append(f"  Dimensions Above 70%: {report.summary_stats['dimensions_above_70']}")
            lines.append(f"  Dimensions Below 50%: {report.summary_stats['dimensions_below_50']}")
            lines.append("")

        if report.improvement_roadmap:
            lines.append("IMPROVEMENT ROADMAP:")
            for i, item in enumerate(report.improvement_roadmap[:5], 1):
                priority_symbol = "[HIGH]" if item["priority"] == "HIGH" else "[MED]" if item["priority"] == "MEDIUM" else "[LOW]"
                lines.append(f"  {i}. {priority_symbol} [{item['dimension']}] {item['suggestion']}")
            lines.append("")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Mode 3: Orchestra Validation (--orchestra)
# ---------------------------------------------------------------------------

def validate_orchestra_skill(filepath: str) -> dict:
    """Validate a single orchestra department skill file and return a score + findings."""
    with open(filepath) as f:
        content = f.read()

    findings = {"pass": [], "fail": [], "warn": [], "score": 0}
    max_score = 0

    # 1. Frontmatter (20 points)
    max_score += 20
    if content.startswith("---"):
        fm_end = content.index("---", 3)
        frontmatter = content[3:fm_end].strip()
        findings["pass"].append("Has frontmatter")
        score = 5

        for field in ["name:", "description:", "metadata:"]:
            if field in frontmatter:
                findings["pass"].append(f"Frontmatter has {field}")
                score += 5
            else:
                findings["fail"].append(f"Frontmatter missing {field}")
        findings["score"] += score
    else:
        findings["fail"].append("No frontmatter (should start with ---)")

    # 2. Title and intro (10 points)
    max_score += 10
    if re.search(r'^# .+', content, re.MULTILINE):
        findings["pass"].append("Has title heading")
        findings["score"] += 5
    else:
        findings["fail"].append("No title heading (# Title)")

    if "You are" in content or "Your goal" in content or "Your job" in content:
        findings["pass"].append("Has agent identity/role statement")
        findings["score"] += 5
    else:
        findings["warn"].append("No clear agent identity statement ('You are...')")

    # 3. Before Starting section (10 points)
    max_score += 10
    if "## Before Starting" in content or "## Before" in content:
        findings["pass"].append("Has 'Before Starting' section")
        findings["score"] += 10
    else:
        findings["warn"].append("No 'Before Starting' section -- agents should check context first")

    # 4. Modes (15 points)
    max_score += 15
    mode_matches = re.findall(r'### Mode \d', content)
    if len(mode_matches) >= 2:
        findings["pass"].append(f"Has {len(mode_matches)} modes")
        findings["score"] += 15
    elif len(mode_matches) == 1:
        findings["pass"].append("Has 1 mode")
        findings["score"] += 8
        findings["warn"].append("Only 1 mode -- consider adding Mode 2 for optimization/follow-up")
    else:
        findings["warn"].append("No modes defined (### Mode N)")

    # 5. Proactive Triggers (15 points)
    max_score += 15
    if "Proactive Trigger" in content or "proactive" in content.lower():
        triggers = re.findall(r'\*\*(.+?)\*\*.*?->', content)
        if triggers:
            findings["pass"].append(f"Has {len(triggers)} proactive triggers")
            findings["score"] += 15
        else:
            findings["pass"].append("Has proactive triggers section")
            findings["score"] += 10
    else:
        findings["warn"].append("No proactive triggers -- agents should flag issues without being asked")

    # 6. Output Artifacts (10 points)
    max_score += 10
    if "Output" in content and ("|" in content):  # Table format
        findings["pass"].append("Has output artifacts table")
        findings["score"] += 10
    elif "Output" in content:
        findings["pass"].append("Has output section")
        findings["score"] += 5
        findings["warn"].append("Output section should use a table format")
    else:
        findings["warn"].append("No output artifacts section")

    # 7. Real Experience / Gotchas (10 points)
    max_score += 10
    gotcha_keywords = ["gotcha", "lesson", "caught", "bug", "mistake", "real experience", "2026-"]
    has_experience = any(kw.lower() in content.lower() for kw in gotcha_keywords)
    if has_experience:
        findings["pass"].append("Contains real experience / lessons learned")
        findings["score"] += 10
    else:
        findings["warn"].append("No gotchas or lessons learned -- skills should encode real experience")

    # 8. Code Examples (10 points)
    max_score += 10
    code_blocks = re.findall(r'```', content)
    if len(code_blocks) >= 4:  # At least 2 code blocks (open + close)
        findings["pass"].append(f"Has {len(code_blocks)//2} code examples")
        findings["score"] += 10
    elif len(code_blocks) >= 2:
        findings["pass"].append("Has code examples")
        findings["score"] += 5
    else:
        findings["warn"].append("No code examples -- concrete examples help agents follow the skill")

    # Calculate percentage
    pct = int((findings["score"] / max_score) * 100) if max_score else 0
    findings["max_score"] = max_score
    findings["percentage"] = pct

    if pct >= 80:
        findings["grade"] = "A"
    elif pct >= 60:
        findings["grade"] = "B"
    elif pct >= 40:
        findings["grade"] = "C"
    else:
        findings["grade"] = "D"

    return findings


def print_orchestra_report(filepath: str, findings: dict):
    """Pretty-print an orchestra validation report."""
    name = os.path.basename(filepath)
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"  Score: {findings['score']}/{findings['max_score']} ({findings['percentage']}%) -- Grade {findings['grade']}")
    print(f"{'='*60}")

    if findings["pass"]:
        for p in findings["pass"]:
            print(f"  PASS: {p}")

    if findings["fail"]:
        for f in findings["fail"]:
            print(f"  FAIL: {f}")

    if findings["warn"]:
        for w in findings["warn"]:
            print(f"  WARN: {w}")

    print()


def run_orchestra_mode(filepath: Optional[str] = None, scan_all: bool = False,
                       json_output: bool = False):
    """Run orchestra validation mode."""
    if scan_all:
        skills = globmod.glob(".orchestra/master/skills/*.md") + \
                 globmod.glob(".orchestra/departments/*/skills/*.md")
        if not skills:
            print("No skills found")
            sys.exit(1)

        total_score = 0
        total_max = 0
        results = []
        for skill in sorted(skills):
            findings = validate_orchestra_skill(skill)
            if json_output:
                results.append({"file": skill, **findings})
            else:
                print_orchestra_report(skill, findings)
            total_score += findings["score"]
            total_max += findings["max_score"]

        avg = int((total_score / total_max) * 100) if total_max else 0
        if json_output:
            print(json.dumps({"skills": results, "total_score": total_score,
                              "total_max": total_max, "average_percentage": avg}, indent=2))
        else:
            print(f"\n{'='*60}")
            print(f"  OVERALL: {total_score}/{total_max} ({avg}%) across {len(skills)} skills")
            print(f"{'='*60}")
    elif filepath:
        if not os.path.exists(filepath):
            print(f"File not found: {filepath}")
            sys.exit(1)
        findings = validate_orchestra_skill(filepath)
        if json_output:
            print(json.dumps({"file": filepath, **findings}, indent=2))
        else:
            print_orchestra_report(filepath, findings)
    else:
        print("Usage: python3 skill_validator.py --orchestra <skill.md>")
        print("       python3 skill_validator.py --orchestra --all")
        sys.exit(1)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Validate skill directories against quality standards",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Modes:
  (default)     Structure validation — checks file layout, frontmatter, scripts
  --quality     Multi-dimensional quality scoring with letter grades
  --orchestra   Validate orchestra department skills (.md files)

Examples:
  python skill_validator.py engineering/my-skill
  python skill_validator.py engineering/my-skill --tier POWERFUL --json
  python skill_validator.py engineering/my-skill --quality --detailed
  python skill_validator.py engineering/my-skill --quality --minimum-score 75
  python skill_validator.py --orchestra skills/deploy-safely/SKILL.md
  python skill_validator.py --orchestra --all
        """
    )

    parser.add_argument("skill_path", nargs="?",
                       help="Path to the skill directory or file to validate")
    parser.add_argument("--tier",
                       choices=["BASIC", "STANDARD", "POWERFUL"],
                       help="Target tier for validation (structure mode)")
    parser.add_argument("--json",
                       action="store_true",
                       help="Output results in JSON format")
    parser.add_argument("--verbose",
                       action="store_true",
                       help="Enable verbose logging")

    # Quality mode flags
    parser.add_argument("--quality",
                       action="store_true",
                       help="Run multi-dimensional quality scoring")
    parser.add_argument("--detailed",
                       action="store_true",
                       help="Show detailed component scores (quality mode)")
    parser.add_argument("--minimum-score",
                       type=float, default=0,
                       help="Minimum acceptable score (quality mode, exit with error if below)")

    # Orchestra mode flags
    parser.add_argument("--orchestra",
                       action="store_true",
                       help="Validate orchestra department skills")
    parser.add_argument("--all",
                       action="store_true",
                       help="Validate all orchestra skills (--orchestra --all)")

    args = parser.parse_args()

    # --- Orchestra mode ---
    if args.orchestra:
        run_orchestra_mode(filepath=args.skill_path, scan_all=args.all,
                           json_output=args.json)
        return

    # Remaining modes require a skill_path
    if not args.skill_path:
        parser.print_help()
        sys.exit(1)

    try:
        # --- Quality mode ---
        if args.quality:
            scorer = QualityScorer(args.skill_path, args.detailed, args.verbose)
            report = scorer.assess_quality()

            if args.json:
                print(QualityReportFormatter.format_json(report))
            else:
                print(QualityReportFormatter.format_human_readable(report, args.detailed))

            if report.overall_score < args.minimum_score:
                print(f"\nERROR: Quality score {report.overall_score:.1f} is below minimum {args.minimum_score}", file=sys.stderr)
                sys.exit(1)

            if report.letter_grade in ("D",):
                sys.exit(2)
            elif report.letter_grade == "F":
                sys.exit(1)
            else:
                sys.exit(0)

        # --- Structure mode (default) ---
        else:
            validator = SkillValidator(args.skill_path, args.tier, args.verbose)
            report = validator.validate_skill_structure()

            if args.json:
                print(ReportFormatter.format_json(report))
            else:
                print(ReportFormatter.format_human_readable(report))

            if report.errors or report.overall_score < 60:
                sys.exit(1)
            else:
                sys.exit(0)

    except KeyboardInterrupt:
        print("\nValidation interrupted by user", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(f"Validation failed: {str(e)}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
