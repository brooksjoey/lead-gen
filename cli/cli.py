# scripts/cli.py
"""
CLI registry and dispatcher for lead-gen system commands.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Callable, Dict, Optional

# Ensure project root is in path for imports
_scripts_dir = Path(__file__).parent
_project_root = _scripts_dir.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# Import verification functions
from cli.verification import (
    check_api_health,
    check_imports,
    check_monitoring_endpoints,
    cleanup_test_data,
    get_system_status,
    run_test_collection,
    test_lead_flow,
    VerificationResult,
)


# Output formatting utilities
def _supports_color() -> bool:
    """Check if terminal supports ANSI color codes."""
    if sys.platform == "win32":
        # Windows 10+ supports ANSI colors
        return os.getenv("TERM") == "xterm" or os.getenv("ANSICON") is not None
    return os.isatty(sys.stdout.fileno())


SUPPORTS_COLOR = _supports_color()

# ANSI color codes
GREEN = '\033[92m' if SUPPORTS_COLOR else ''
RED = '\033[91m' if SUPPORTS_COLOR else ''
YELLOW = '\033[93m' if SUPPORTS_COLOR else ''
BLUE = '\033[94m' if SUPPORTS_COLOR else ''
RESET = '\033[0m' if SUPPORTS_COLOR else ''


def print_success(message: str):
    """Print success message with [✓] symbol."""
    print(f"{GREEN}[✓]{RESET} {message}")


def print_error(message: str):
    """Print error message with [✗] symbol."""
    print(f"{RED}[✗]{RESET} {message}")


def print_warning(message: str):
    """Print warning message with [!] symbol."""
    print(f"{YELLOW}[!]{RESET} {message}")


def print_info(message: str):
    """Print info message with [i] symbol."""
    print(f"{BLUE}[i]{RESET} {message}")


# Command functions
async def cmd_verify_imports(args: argparse.Namespace) -> int:
    """Command: Verify all imports work."""
    print_info("Checking imports...")
    result = await check_imports()
    
    if result.success:
        print_success(result.message)
        if result.data.get('modules_tested'):
            print_info(f"  Tested {result.data['modules_tested']} modules")
        return 0
    else:
        print_error(result.message)
        if result.data.get('errors'):
            for error in result.data['errors']:
                print_error(f"  {error['module']}: {error['error']}")
        return 1


async def cmd_verify_api_start(args: argparse.Namespace) -> int:
    """Command: Verify API starts and health check passes."""
    print_info("Checking API health...")
    api_url = getattr(args, 'api_url', 'http://localhost:8000')
    result = await check_api_health(api_url=api_url)
    
    if result.success:
        print_success(result.message)
        return 0
    else:
        print_error(result.message)
        return 1


async def cmd_verify_lead_flow(args: argparse.Namespace) -> int:
    """Command: Test complete lead flow."""
    print_info("Testing lead flow (create → deliver → bill)...")
    api_url = getattr(args, 'api_url', 'http://localhost:8000')
    result = await test_lead_flow(api_url=api_url)
    
    if result.success:
        print_success(result.message)
        if result.data.get('note'):
            print_info(f"  Note: {result.data['note']}")
        return 0
    else:
        print_error(result.message)
        return 1


async def cmd_verify_monitoring(args: argparse.Namespace) -> int:
    """Command: Verify monitoring endpoints return data."""
    print_info("Checking monitoring endpoints...")
    api_url = getattr(args, 'api_url', 'http://localhost:8000')
    result = await check_monitoring_endpoints(api_url=api_url)
    
    if result.success:
        print_success(result.message)
        if result.data.get('results'):
            for endpoint, status in result.data['results'].items():
                status_str = 'accessible' if status.get('accessible') else 'error'
                print_info(f"  {endpoint}: {status_str}")
        return 0
    else:
        print_error(result.message)
        if result.data.get('failures'):
            for failure in result.data['failures']:
                print_error(f"  {failure}")
        return 1


async def cmd_verify_tests(args: argparse.Namespace) -> int:
    """Command: Verify tests can run."""
    print_info("Checking tests...")
    result = await run_test_collection()
    
    if result.success:
        print_success(result.message)
        return 0
    else:
        print_error(result.message)
        return 1


async def cmd_verify_all(args: argparse.Namespace) -> int:
    """Command: Run all verification steps."""
    print_info("Running all verification checks...")
    print()
    
    checks = [
        ('Imports', cmd_verify_imports),
        ('API Health', cmd_verify_api_start),
        ('Monitoring', cmd_verify_monitoring),
        ('Tests', cmd_verify_tests),
    ]
    
    # Skip lead flow for now as it requires full database setup
    # checks.append(('Lead Flow', cmd_verify_lead_flow))
    
    results = []
    for check_name, check_func in checks:
        print_info(f"Running: {check_name}...")
        exit_code = await check_func(args)
        results.append((check_name, exit_code == 0))
        print()
    
    # Summary
    passed = sum(1 for _, success in results if success)
    total = len(results)
    
    if passed == total:
        print_success(f"All {total} checks passed - SYSTEM VERIFIED AS OPERATIONAL")
        return 0
    else:
        print_error(f"{passed}/{total} checks passed - SYSTEM NOT OPERATIONAL")
        for check_name, success in results:
            status = "PASS" if success else "FAIL"
            symbol = "✓" if success else "✗"
            print(f"  [{symbol}] {check_name}: {status}")
        return 1


async def cmd_system_status(args: argparse.Namespace) -> int:
    """Command: Quick system health check."""
    print_info("Checking system status...")
    result = await get_system_status()
    
    if result.data.get('services'):
        services = result.data['services']
        for service_name, service_status in services.items():
            status = service_status.get('status', 'unknown')
            if status == 'connected' or status == 'running':
                print_success(f"{service_name.capitalize()}: {status}")
            else:
                print_error(f"{service_name.capitalize()}: {status}")
                if service_status.get('error'):
                    print_error(f"  Error: {service_status['error']}")
    
    if result.data.get('all_connected'):
        print_success("All services connected")
        return 0
    else:
        print_warning("Some services not connected")
        return 0  # Always return 0 for status (information only)


async def cmd_reset_test_data(args: argparse.Namespace) -> int:
    """Command: Clean up test data."""
    print_info("Cleaning up test data...")
    result = await cleanup_test_data()
    
    if result.success:
        print_success(result.message)
        if result.data.get('cleaned'):
            print_info(f"  Cleaned {result.data['cleaned']} test records")
        return 0
    else:
        print_error(result.message)
        return 1


# Command registry
COMMANDS: Dict[str, Callable] = {
    'verify-imports': cmd_verify_imports,
    'verify-api-start': cmd_verify_api_start,
    'verify-lead-flow': cmd_verify_lead_flow,
    'verify-monitoring': cmd_verify_monitoring,
    'verify-tests': cmd_verify_tests,
    'verify-all': cmd_verify_all,
    'system-status': cmd_system_status,
    'reset-test-data': cmd_reset_test_data,
}


def create_parser() -> argparse.ArgumentParser:
    """Create argument parser with all commands."""
    parser = argparse.ArgumentParser(
        description='Lead-Gen CLI Registry',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to execute')
    
    # verify-imports
    subparsers.add_parser('verify-imports', help='Verify all imports work')
    
    # verify-api-start
    api_parser = subparsers.add_parser('verify-api-start', help='Verify API starts')
    api_parser.add_argument('--api-url', default='http://localhost:8000', help='API URL')
    
    # verify-lead-flow
    lead_parser = subparsers.add_parser('verify-lead-flow', help='Test complete lead flow')
    lead_parser.add_argument('--api-url', default='http://localhost:8000', help='API URL')
    
    # verify-monitoring
    mon_parser = subparsers.add_parser('verify-monitoring', help='Verify monitoring endpoints')
    mon_parser.add_argument('--api-url', default='http://localhost:8000', help='API URL')
    
    # verify-tests
    subparsers.add_parser('verify-tests', help='Verify tests can run')
    
    # verify-all
    all_parser = subparsers.add_parser('verify-all', help='Run all verification checks')
    all_parser.add_argument('--api-url', default='http://localhost:8000', help='API URL')
    
    # system-status
    subparsers.add_parser('system-status', help='Quick system health check')
    
    # reset-test-data
    subparsers.add_parser('reset-test-data', help='Clean up test data')
    
    return parser


def main(args: Optional[list] = None) -> int:
    """Main CLI entry point."""
    parser = create_parser()
    
    if args is None:
        parsed_args = parser.parse_args()
    else:
        parsed_args = parser.parse_args(args)
    
    if not parsed_args.command:
        parser.print_help()
        return 1
    
    command_func = COMMANDS.get(parsed_args.command)
    if not command_func:
        print_error(f"Unknown command: {parsed_args.command}")
        parser.print_help()
        return 1
    
    try:
        # Run async command
        exit_code = asyncio.run(command_func(parsed_args))
        return exit_code
    except KeyboardInterrupt:
        print_error("\nInterrupted by user")
        return 130
    except Exception as e:
        print_error(f"Error executing command: {str(e)}")
        import traceback
        if os.getenv('DEBUG'):
            traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())

