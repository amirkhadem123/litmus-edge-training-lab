# Screenshots

Each scenario requires pre-captured screenshots that are uploaded as Zendesk ticket attachments.
Screenshots should be captured from a real or mock Litmus Edge 4.x UI.

## Required files

### le-s01 (Stopped Device)
- `le-s01/devicehub_overview.png` — DeviceHub list showing PLC-Line3 with a red/stopped status badge
- `le-s01/tag_data_gap.png` — Tag value history table or chart showing data stopping ~90 minutes ago

### le-s02 (No Tags)
- `le-s02/device_detail_running.png` — Device detail page showing Running state but empty tags list
- `le-s02/historian_empty_result.png` — Historian query returning zero results for this device

### le-s03 (SSH Stopped)
- `le-s03/ssh_connection_refused.png` — Terminal output: `ssh user@ip` → `Connection refused`
- `le-s03/system_services_page.png` — Litmus Edge System → Services page showing SSH service as Stopped

### le-s04 (Viewer Permissions)
- `le-s04/device_view_greyed_buttons.png` — DeviceHub device page with Edit/Start/Stop buttons greyed out
- `le-s04/user_account_settings.png` — Admin user settings page showing dpark assigned to Viewers group

### le-s05 (Auth Service Crash)
- `le-s05/auth_error_logs.png` — System logs showing repeated auth service memory/crash errors
- `le-s05/login_spinner_loop.png` — Browser showing login spinner then redirect (capture as sequence or GIF)

### le-s06 (Data Corruption)
- `le-s06/historian_impossible_values.png` — Chart showing INT32_MAX (2,147,483,647) and negative values
- `le-s06/tag_config_int32.png` — Tag configuration page showing the int32 data type setting

## Tips
- Use the existing LE 4.0.6 test instance at https://10.88.111.19 to capture real screenshots
- For scenarios requiring broken states (le-s01, le-s03): use the existing Phase 1 scenario
  scripts in `app/scenarios/archive/` to create those states temporarily for screenshotting
- For le-s05 and le-s06: mock the screenshots in an image editor if a real broken instance
  isn't available — the log text and values just need to look plausible
