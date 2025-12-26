# Troubleshooting

Common issues and solutions for ZotMD.

## Installation Issues

### Command not found: zotmd

**Problem:**
```bash
$ zotmd --help
zotmd: command not found
```

**Solutions:**

1. **If installed with uv:**
   ```bash
   # Ensure uv's bin directory is in PATH
   echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
   source ~/.zshrc

   # Verify installation
   uv tool list
   ```

2. **If installed with pipx:**
   ```bash
   # Ensure pipx path
   pipx ensurepath
   source ~/.zshrc
   ```

3. **Reinstall:**
   ```bash
   uv tool install --force zotmd
   ```

### Python version too old

**Problem:**
```bash
ERROR: Package requires Python >=3.13
```

**Solution:**
```bash
# Install Python 3.13+ with uv
uv python install 3.13

# Or use system package manager
# macOS:
brew install python@3.13

# Linux:
sudo apt install python3.13
```

## Connection Issues

### Cannot connect to Zotero

**Problem:**
```bash
$ zotmd status
✗ Error: Connection refused
```

**Solutions:**

1. **Enable API access:**
   - Zotero → Settings → Advanced → Miscellaneous
   - Check "Allow other applications to access Zotero"

2. **Verify credentials:**
   ```bash
   zotmd init  # Re-enter credentials
   ```

3. **Test API manually:**
   ```bash
   curl "https://api.zotero.org/users/YOUR_ID/items?limit=1&key=YOUR_KEY"
   ```

### 403 Forbidden Error

**Problem:**
```bash
✗ Error: 403 Forbidden
```

**Causes & Solutions:**

1. **Wrong library_type:**
   - Personal library: Use `library_type = "user"`
   - Group library: Use `library_type = "group"`

2. **Invalid API key:**
   - Regenerate at [zotero.org/settings/keys/new](https://www.zotero.org/settings/keys/new)
   - Ensure "Allow library access" is checked

3. **Wrong library ID:**
   - Verify at [zotero.org/settings/keys](https://www.zotero.org/settings/keys)
   - For groups: Use group ID, not user ID

### Rate Limiting

**Problem:**
```bash
✗ Error: 429 Too Many Requests
```

**Solution:**
Wait a few minutes before retrying. Zotero API has rate limits:
- Personal tier: 120 requests/minute
- Group tier: Shared across all members

## Sync Issues

### Items missing citation keys

**Problem:**
```bash
Skipped 45 items without citation keys
```

**Solution:**

1. **Install Better BibTeX:**
   - Download: [retorque.re/zotero-better-bibtex](https://retorque.re/zotero-better-bibtex/)
   - Zotero → Tools → Add-ons → Install from File

2. **Generate citation keys:**
   - Select all items in Zotero
   - Right-click → Better BibTeX → Refresh BibTeX key

3. **Re-sync:**
   ```bash
   zotmd sync
   ```

### Annotations not appearing

**Problem:**
PDF highlights not showing in Markdown files.

**Solutions:**

1. **Ensure PDF is in Zotero:**
   - Attachment must be stored in Zotero (not linked file)
   - Check: Item has PDF icon, not link icon

2. **Annotations must be created in Zotero:**
   - Use Zotero's built-in PDF reader
   - External annotations (Adobe, Preview) won't sync

3. **Force re-sync:**
   ```bash
   zotmd sync --full
   ```

### Deleted items reappearing

**Problem:**
Deleted Markdown files come back after sync.

**Cause:**
Items still exist in Zotero library.

**Solution:**

1. **Delete from Zotero first:**
   - Delete item in Zotero
   - Empty Zotero trash
   - Run `zotmd sync`

2. **Or remove from filesystem only:**
   - Set `deletion_behavior = "delete"` in config
   - Files won't be recreated if deleted locally

### User notes being overwritten

**Problem:**
Custom notes in Markdown files are lost after sync.

**Solution:**

Place notes in the designated section:

```markdown
## Notes
<!-- Add your notes below this line -->
<!-- They will be preserved across syncs -->

Your custom notes here...
```

Content above this section will be regenerated on each sync.

## Database Issues

### Corrupted database

**Problem:**
```bash
Error: database disk image is malformed
```

**Solution:**

1. **Backup current database:**
   ```bash
   # macOS
   cp ~/.local/share/zotmd/sync.sqlite ~/sync.sqlite.backup

   # Linux
   cp ~/.local/share/zotmd/sync.sqlite ~/sync.sqlite.backup
   ```

2. **Delete and re-sync:**
   ```bash
   rm ~/.local/share/zotmd/sync.sqlite
   zotmd sync --full
   ```

### Database locked

**Problem:**
```bash
Error: database is locked
```

**Solution:**

1. **Check for other zotmd processes:**
   ```bash
   ps aux | grep zotmd
   kill <PID>  # If found
   ```

2. **Remove lock file:**
   ```bash
   rm ~/.local/share/zotmd/sync.sqlite-journal
   ```

## File System Issues

### Permission denied

**Problem:**
```bash
Error: Permission denied: /path/to/output
```

**Solutions:**

1. **Create directory:**
   ```bash
   mkdir -p ~/notes/references
   ```

2. **Fix permissions:**
   ```bash
   chmod 755 ~/notes/references
   ```

3. **Choose different path:**
   ```bash
   zotmd init  # Enter accessible directory
   ```

### Filename too long

**Problem:**
```bash
OSError: File name too long
```

**Cause:**
Citation keys longer than filesystem limit (255 chars).

**Solution:**

1. **Shorten citation key in Better BibTeX:**
   - Right-click item → Better BibTeX → Pin/Set citation key
   - Enter shorter key

2. **Change citation key pattern:**
   - Zotero Settings → Better BibTeX → Citation Keys
   - Use shorter pattern (e.g., `[auth:lower][year]`)

### Special characters in filenames

**Problem:**
Files with invalid characters (`/`, `:`, `*`, etc.)

**Solution:**

ZotMD automatically sanitizes filenames, but if issues persist:

1. **Check citation key:**
   - Avoid: `< > : " / \ | ? *`
   - Better BibTeX usually handles this

2. **Manually fix:**
   - Edit citation key in Zotero
   - Remove problematic characters

## Template Issues

### Template not found

**Problem:**
```bash
Error: Template file not found: /path/to/template.md.j2
```

**Solutions:**

1. **Verify path:**
   ```bash
   ls -l /path/to/template.md.j2
   ```

2. **Use absolute path in config:**
   ```toml
   template_path = "/Users/me/templates/custom.md.j2"
   ```

3. **Reset to default:**
   ```toml
   template_path = ""  # Empty uses built-in
   ```

### Template syntax error

**Problem:**
```bash
jinja2.exceptions.TemplateSyntaxError: unexpected '}'
```

**Solution:**

1. **Validate Jinja2 syntax:**
   - Check matching `{% ... %}`, `{{ ... }}`
   - Ensure proper indentation

2. **Test with default template:**
   ```toml
   template_path = ""
   ```
   ```bash
   zotmd sync --full
   ```

3. **Debug template:**
   ```bash
   zotmd sync --verbose
   ```

## Performance Issues

### Sync is very slow

**Problem:**
Full sync takes hours for large library.

**Solutions:**

1. **Use incremental sync:**
   ```bash
   zotmd sync  # Default, not --full
   ```

2. **Check network:**
   - Zotero API may be slow
   - Try at different time

3. **Reduce annotation processing:**
   - Large PDFs with many annotations take time
   - This is expected behavior

### High memory usage

**Problem:**
Process using excessive RAM.

**Cause:**
Large library with many annotations.

**Mitigation:**

1. **Process in batches** (not yet supported - feature request)
2. **Close other applications**
3. **Increase system swap space**

## Getting Help

If you encounter an issue not listed here:

1. **Check existing issues:**
   [github.com/adhithyabhaskar/zotmd/issues](https://github.com/adhithyabhaskar/zotmd/issues)

2. **Run with verbose logging:**
   ```bash
   zotmd sync --verbose 2>&1 | tee debug.log
   ```

3. **Create new issue with:**
   - Error message
   - Steps to reproduce
   - `debug.log` output
   - OS and Python version
   - `zotmd status` output

## Useful Diagnostic Commands

```bash
# Check config
zotmd status

# Test connection only
zotmd init  # Will test during setup

# View config file
cat ~/.config/zotmd/config.toml  # macOS/Linux

# Check database
sqlite3 ~/.local/share/zotmd/sync.sqlite "SELECT COUNT(*) FROM sync_items;"

# List installed version
uv tool list | grep zotmd
```
