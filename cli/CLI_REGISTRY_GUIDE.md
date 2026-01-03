# CLI Registry Guide

Complete guide for using and extending the Lead-Gen CLI registry system.

## Quick Start

### Most Common Commands

```bash
# Verify system is operational (runs all checks)
lg verify-all

# Quick system status check
lg status

# Test lead flow (create → deliver → bill)
lg test-flow

# Check system status
lg system-status
```

### Running Commands

You can run commands in two ways:

1. **Using main CLI entry point:**
   ```bash
   lg verify-all
   lg system-status
   ```

2. **Using individual command wrappers:**
   ```bash
   lg-verify-all
   lg-system-status
   ```

## Command Reference

### Verification Commands

| Command | Alias | Description | Exit Code |
|---------|-------|-------------|-----------|
| `lg verify-imports` | `lg-check-imports` | Verify all Python modules can be imported | 0=success, 1=failed |
| `lg verify-api-start` | `lg-check-api` | Verify API starts and health check passes | 0=success, 1=failed |
| `lg verify-lead-flow` | `lg-test-flow` | Test complete lead flow (create → deliver → bill) | 0=success, 1=failed |
| `lg verify-monitoring` | - | Verify monitoring endpoints return data | 0=success, 1=failed |
| `lg verify-tests` | - | Verify tests can be collected and run | 0=success, 1=failed |
| `lg verify-all` | `lg-test-system` | Run all verification checks | 0=success, 1=failed |

### System Commands

| Command | Alias | Description | Exit Code |
|---------|-------|-------------|-----------|
| `lg system-status` | `lg-status` | Quick system health check (DB, Redis, API) | Always 0 (info only) |
| `lg reset-test-data` | `lg-cleanup` | Clean up test data from verification | 0=success, 1=failed |

### Command Options

Some commands support options:

```bash
# Specify API URL
lg verify-api-start --api-url http://localhost:8080
lg verify-monitoring --api-url http://localhost:8080
lg verify-lead-flow --api-url http://localhost:8080
lg verify-all --api-url http://localhost:8080
```

## Verification Criteria

A system is considered **operational** when:

1. ✅ **All imports work** - No ModuleNotFoundError when importing key modules
2. ✅ **API starts** - API health endpoint responds successfully
3. ✅ **Monitoring endpoints work** - All monitoring endpoints return data
4. ✅ **Tests can run** - pytest can collect tests without errors
5. ✅ **Lead flow works** - Can create lead → deliver → bill (optional, requires DB setup)

### Running Full Verification

```bash
lg verify-all
```

Expected output when system is operational:
```
[i] Running all verification checks...

[i] Running: Imports...
[✓] Successfully imported 20 modules
  Tested 20 modules

[i] Running: API Health...
[✓] API health check passed

[i] Running: Monitoring...
[✓] All 3 monitoring endpoints accessible
  /api/health: accessible
  /api/health/live: accessible
  /api/health/ready: accessible

[i] Running: Tests...
[✓] Tests can be collected successfully

[✓] All 4 checks passed - SYSTEM VERIFIED AS OPERATIONAL
```

## Detailed Command Documentation

### lg verify-imports

Verifies that all critical Python modules can be imported without errors.

**What it checks:**
- Core modules (config, exceptions, logging, db)
- Service modules (billing, classification, delivery, routing, validation)
- Route modules (leads, buyers, health, monitoring)
- Model modules (lead, base)
- Main application module

**Example:**
```bash
lg verify-imports
```

**Success criteria:** All modules import without ModuleNotFoundError

### lg verify-api-start

Checks if the API is running and the health endpoint responds.

**What it checks:**
- API is accessible at specified URL (default: http://localhost:8000)
- `/api/health/live` endpoint returns 200 OK

**Example:**
```bash
lg verify-api-start
lg verify-api-start --api-url http://localhost:8080
```

**Success criteria:** API health endpoint returns 200 OK

### lg verify-lead-flow

Tests the complete lead flow: create → deliver → bill.

**What it checks:**
- API is accessible
- (Full test requires database setup with test data)

**Note:** Full lead flow test requires:
- Database with test buyers, offers, markets, verticals
- Authentication configured
- Delivery queue running
- Billing system configured

**Example:**
```bash
lg verify-lead-flow
```

### lg verify-monitoring

Verifies that monitoring endpoints return data.

**What it checks:**
- `/api/health` - Full health check
- `/api/health/live` - Liveness probe
- `/api/health/ready` - Readiness probe

**Example:**
```bash
lg verify-monitoring
```

**Success criteria:** All endpoints return status codes < 500

### lg verify-tests

Verifies that tests can be discovered and collected.

**What it checks:**
- pytest can run with --collect-only
- No import errors in test files
- Tests can be discovered

**Example:**
```bash
lg verify-tests
```

**Success criteria:** pytest --collect-only exits with code 0

### lg verify-all

Runs all verification checks in sequence.

**What it checks:**
- Imports
- API health
- Monitoring endpoints
- Test collection

**Example:**
```bash
lg verify-all
```

**Success criteria:** All checks pass

### lg system-status

Quick system health check showing status of all services.

**What it checks:**
- Database connection
- Redis connection
- API status

**Example:**
```bash
lg system-status
```

**Note:** Always returns exit code 0 (information only)

### lg reset-test-data

Cleans up test data created during verification.

**Example:**
```bash
lg reset-test-data
```

## Troubleshooting

### Import Errors

**Problem:** `lg verify-imports` fails with ModuleNotFoundError

**Solutions:**
- Ensure you're in the project root directory
- Check PYTHONPATH includes the project root
- Verify all dependencies are installed: `pip install -r api/requirements.txt`
- Check for circular imports in the codebase

### API Not Starting

**Problem:** `lg verify-api-start` fails - API not accessible

**Solutions:**
- Check if API is running: `curl http://localhost:8000/api/health/live`
- Start API: `uvicorn api.main:app --host 0.0.0.0 --port 8000`
- Check if port 8000 is available
- Verify API_URL if using custom port: `lg verify-api-start --api-url http://localhost:8080`

### Database Connection Errors

**Problem:** `lg system-status` shows database error

**Solutions:**
- Check database is running: `docker compose ps postgres`
- Verify DATABASE_URL in .env file
- Test connection: `psql $DATABASE_URL`
- Check database credentials

### Redis Connection Errors

**Problem:** `lg system-status` shows Redis error

**Solutions:**
- Check Redis is running: `docker compose ps redis`
- Verify REDIS_URL in .env file
- Test connection: `redis-cli ping`
- Check Redis credentials

### Test Collection Fails

**Problem:** `lg verify-tests` fails

**Solutions:**
- Run pytest manually: `pytest --collect-only tests/`
- Check for import errors in test files
- Verify pytest is installed: `pip install pytest pytest-asyncio`
- Check PYTHONPATH

## Integration with Development Workflow

### Pre-commit Hooks

Add to `.git/hooks/pre-commit`:

```bash
#!/bin/bash
lg verify-imports || exit 1
lg verify-tests || exit 1
```

### CI/CD Pipeline

Add to your CI pipeline:

```yaml
# Example GitHub Actions
- name: Verify System
  run: |
    lg verify-all
```

### Manual Testing

Before deploying or making major changes:

```bash
# Full verification
lg verify-all

# Quick status check
lg status
```

### Production Deployment

Before deploying to production:

```bash
# Verify all checks pass
lg verify-all

# Check system status
lg system-status
```

## Adding New Commands

The CLI registry is designed to be easily extensible. To add a new command:

### Step 1: Add Verification Function (if needed)

If the command needs shared logic, add it to `scripts/verification.py`:

```python
async def your_new_function() -> VerificationResult:
    """Your new verification function."""
    # Implementation
    return VerificationResult(success=True, message="Done", data={})
```

### Step 2: Add Command Function

Add command handler to `scripts/cli.py`:

```python
async def cmd_your_new_command(args: argparse.Namespace) -> int:
    """Command: Your new command description."""
    print_info("Running your command...")
    result = await your_new_function()
    
    if result.success:
        print_success(result.message)
        return 0
    else:
        print_error(result.message)
        return 1
```

### Step 3: Register Command

Add to COMMANDS registry in `scripts/cli.py`:

```python
COMMANDS = {
    # ... existing commands ...
    'your-new-command': cmd_your_new_command,
}
```

### Step 4: Add Parser

Add subparser in `create_parser()` function:

```python
subparsers.add_parser('your-new-command', help='Your command description')
```

### Step 5: Create Wrapper Script

Create `scripts/lg_your_new_command.py`:

```python
#!/usr/bin/env python
"""Command wrapper: your-new-command"""
import sys
from scripts.cli import main

if __name__ == '__main__':
    sys.exit(main(['your-new-command'] + sys.argv[1:]))
```

### Step 6: Create Batch Wrapper

Create `lg-your-new-command.bat`:

```batch
@echo off
python scripts\lg_your_new_command.py %*
exit /b %ERRORLEVEL%
```

### Step 7: Update Documentation

Add your command to this guide's Command Reference section.

## Future Commands

The CLI registry can be extended with commands for:

- **Database operations:** `lg-migrate`, `lg-migrate-up`, `lg-migrate-down`
- **Data management:** `lg-seed-buyers`, `lg-seed-test-data`, `lg-export-leads`, `lg-import-leads`
- **Backup/Restore:** `lg-backup`, `lg-restore`
- **Configuration:** `lg-config-check`, `lg-config-validate`
- **Logs:** `lg-logs`, `lg-logs-tail`
- **Performance:** `lg-benchmark`, `lg-load-test`

## Getting Help

Run any command with `--help` for usage information:

```bash
lg --help
lg verify-all --help
lg system-status --help
```

## Exit Codes

- **0** - Success
- **1** - Failure/Error
- **130** - Interrupted (Ctrl+C)

The `system-status` command always returns 0 (information only, not a pass/fail check).

