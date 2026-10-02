/* installer.c — one-click Windows setup for opngx (v2.1: rewritten).
 *
 * Installs per user (%LOCALAPPDATA%\opngx, no admin rights): the studio
 * (opngx-studio.exe), the command-line engine (opngx-engine.exe), the docs
 * and an uninstaller (a copy of this program). Adds the folder to the user
 * PATH, registers an "Apps & features" entry, creates Start-menu (and
 * optionally desktop) shortcuts to the studio.
 *
 *   opngx-setup.exe              interactive
 *   opngx-setup.exe /S           silent install (exit code 0 = ok)
 *   uninstall.exe --uninstall    remove (what Apps & features runs)
 *   uninstall.exe --uninstall /S silent removal
 *
 * Everything uses the wide-character (UTF-16) Windows API so profile
 * folders such as C:\Users\José or C:\Users\李 work.
 *
 * v2.1 fixes (all found by a bug hunt and reproduced under Wine):
 *  - the user PATH was read with RRF_RT_REG_EXPAND_SZ but without
 *    RRF_NOEXPAND, which RegGetValue rejects (ERROR_INVALID_PARAMETER);
 *    the failure was taken for "no PATH" and PATH was REPLACED by the
 *    install folder, deleting every other entry. Now: RRF_NOEXPAND, type
 *    preserved, and any read failure other than "value not found" leaves
 *    PATH untouched;
 *  - "is it already on PATH" / "remove from PATH" matched any entry that
 *    merely CONTAINED "\opngx" (e.g. D:\opngx-dev\build); now exact,
 *    case-insensitive entry comparison with the install folder;
 *  - Uninstall ran "opngx-engine.exe --uninstall", an option the engine
 *    does not have: uninstalling did nothing. The setup now copies itself
 *    as uninstall.exe and registers that;
 *  - shortcuts launched the console CLI instead of the studio;
 *  - uninstall looked for the docs in <install>\docs\docs and left both
 *    folders behind;
 *  - ANSI paths (SHGetFolderPathA) converted as UTF-8 broke non-ASCII
 *    profile names;
 *  - installing while opngx ran failed with "Payload extraction failed".
 *
 * Build (MinGW):
 *   windres app.rc -O coff -o apprc.o
 *   gcc -O2 -mwindows -municode installer.c apprc.o -o opngx-setup.exe \
 *       -lole32 -luuid -lshell32 -ladvapi32 -static
 */
#define WIN32_LEAN_AND_MEAN
#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#include <windows.h>
#include <shlobj.h>
#include <shellapi.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>

#define RES_ENGINE 101
#define RES_STUDIO 102
#define RES_DOCS   103
#define APP_VERSION "2.1.0"
#define APP_VERSION_W L"2.1.0"
#define APP_NAME_W  L"opngx"
#define PUBLISHER_W L"opngx contributors"
#define UNINST_KEY  L"Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\opngx"

#define PATHMAX 1024
static wchar_t g_install[PATHMAX];   /* %LOCALAPPDATA%\opngx */
static wchar_t g_engine[PATHMAX];
static wchar_t g_studio[PATHMAX];
static wchar_t g_uninst[PATHMAX];
static wchar_t g_docs[PATHMAX];
static int g_silent = 0;

static void build_paths(void) {
    wchar_t base[MAX_PATH];
    if (FAILED(SHGetFolderPathW(NULL, CSIDL_LOCAL_APPDATA, NULL, 0, base)))
        wcscpy(base, L"C:\\");
    _snwprintf(g_install, PATHMAX, L"%ls\\%ls", base, APP_NAME_W);
    _snwprintf(g_engine, PATHMAX, L"%ls\\opngx-engine.exe", g_install);
    _snwprintf(g_studio, PATHMAX, L"%ls\\opngx-studio.exe", g_install);
    _snwprintf(g_uninst, PATHMAX, L"%ls\\uninstall.exe", g_install);
    _snwprintf(g_docs, PATHMAX, L"%ls\\docs", g_install);
}

static int ask(const wchar_t *text, const wchar_t *title, UINT flags) {
    return g_silent ? IDOK : MessageBoxW(NULL, text, title, flags);
}

/* ------------------------------------------------------------- files -- */
/* Write RCDATA resource `id` to `dest`. 0 ok, -1 no resource, -2 cannot
 * create (in use?), -3 write failed. */
static int extract_rc(int id, const wchar_t *dest) {
    HRSRC hr = FindResourceW(NULL, MAKEINTRESOURCEW(id), (LPCWSTR)RT_RCDATA);
    if (!hr) return -1;
    HGLOBAL hg = LoadResource(NULL, hr);
    const void *data = hg ? LockResource(hg) : NULL;
    DWORD size = SizeofResource(NULL, hr);
    if (!data || !size) return -1;
    HANDLE fh = CreateFileW(dest, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (fh == INVALID_HANDLE_VALUE) return -2;
    DWORD off = 0;
    while (off < size) {
        DWORD w = 0;
        if (!WriteFile(fh, (const char *)data + off, size - off, &w, NULL) || !w) {
            CloseHandle(fh);
            return -3;
        }
        off += w;
    }
    CloseHandle(fh);
    return 0;
}

/* A running exe cannot be opened for exclusive write. */
static int file_in_use(const wchar_t *path) {
    if (GetFileAttributesW(path) == INVALID_FILE_ATTRIBUTES) return 0;
    HANDLE h = CreateFileW(path, GENERIC_WRITE, 0, NULL, OPEN_EXISTING, 0, NULL);
    if (h == INVALID_HANDLE_VALUE) return GetLastError() == ERROR_SHARING_VIOLATION;
    CloseHandle(h);
    return 0;
}

/* Wait until neither program is running (or the user gives up). */
static int ensure_not_running(const wchar_t *what) {
    while (file_in_use(g_studio) || file_in_use(g_engine)) {
        if (g_silent) return 0;
        wchar_t msg[512];
        _snwprintf(msg, 512, L"opngx is running.\n\nClose the opngx studio (and any opngx-engine "
                             L"window), then click Retry to %ls.", what);
        if (MessageBoxW(NULL, msg, L"opngx", MB_RETRYCANCEL | MB_ICONWARNING) != IDRETRY) return 0;
    }
    return 1;
}

/* Recursive delete of a folder (no UI). */
static void delete_tree(const wchar_t *dir) {
    size_t n = wcslen(dir);
    wchar_t *from = (wchar_t *)calloc(n + 2, sizeof(wchar_t)); /* double-NUL terminated */
    if (!from) return;
    wcscpy(from, dir);
    SHFILEOPSTRUCTW op;
    ZeroMemory(&op, sizeof op);
    op.wFunc = FO_DELETE;
    op.pFrom = from;
    op.fFlags = FOF_NO_UI;
    SHFileOperationW(&op);
    free(from);
}

/* ---------------------------------------------------------- registry -- */
static void set_sz(const wchar_t *name, const wchar_t *value) {
    HKEY h;
    if (RegCreateKeyExW(HKEY_CURRENT_USER, UNINST_KEY, 0, NULL, 0, KEY_SET_VALUE, NULL, &h, NULL) != ERROR_SUCCESS)
        return;
    RegSetValueExW(h, name, 0, REG_SZ, (const BYTE *)value, (DWORD)((wcslen(value) + 1) * sizeof(wchar_t)));
    RegCloseKey(h);
}

static void set_dword(const wchar_t *name, DWORD v) {
    HKEY h;
    if (RegCreateKeyExW(HKEY_CURRENT_USER, UNINST_KEY, 0, NULL, 0, KEY_SET_VALUE, NULL, &h, NULL) != ERROR_SUCCESS)
        return;
    RegSetValueExW(h, name, 0, REG_DWORD, (const BYTE *)&v, sizeof v);
    RegCloseKey(h);
}

static DWORD file_kib(const wchar_t *p) {
    WIN32_FILE_ATTRIBUTE_DATA a;
    if (!GetFileAttributesExW(p, GetFileExInfoStandard, &a)) return 0;
    ULONGLONG s = ((ULONGLONG)a.nFileSizeHigh << 32) | a.nFileSizeLow;
    return (DWORD)(s / 1024);
}

static void register_uninstall(void) {
    wchar_t cmd[PATHMAX + 32];
    _snwprintf(cmd, PATHMAX + 32, L"\"%ls\" --uninstall", g_uninst);
    wchar_t quiet[PATHMAX + 40];
    _snwprintf(quiet, PATHMAX + 40, L"\"%ls\" --uninstall /S", g_uninst);
    set_sz(L"DisplayName", L"opngx studio");
    set_sz(L"DisplayVersion", APP_VERSION_W);
    set_sz(L"Publisher", PUBLISHER_W);
    set_sz(L"InstallLocation", g_install);
    set_sz(L"DisplayIcon", g_studio);
    set_sz(L"UninstallString", cmd);
    set_sz(L"QuietUninstallString", quiet);
    set_sz(L"HelpLink", L"https://github.com/Shuvam-Banerji-Seal/opngx");
    set_dword(L"NoModify", 1);
    set_dword(L"NoRepair", 1);
    set_dword(L"EstimatedSize", file_kib(g_studio) + file_kib(g_engine) + file_kib(g_uninst));
}

/* --------------------------------------------------------------- PATH -- */
#define PATH_LIMIT 32767

/* 1 = read into *out (type in *type), 0 = no PATH value, -1 = error:
 * the caller must then leave PATH alone. */
static int read_user_path(wchar_t **out, DWORD *type) {
    DWORD bytes = 0, t = 0;
    const DWORD fl = RRF_RT_REG_SZ | RRF_RT_REG_EXPAND_SZ | RRF_NOEXPAND;
    LONG rc = RegGetValueW(HKEY_CURRENT_USER, L"Environment", L"Path", fl, &t, NULL, &bytes);
    if (rc == ERROR_FILE_NOT_FOUND) return 0;
    if (rc != ERROR_SUCCESS || bytes == 0) return -1;
    if (bytes / sizeof(wchar_t) > PATH_LIMIT) return -1;
    wchar_t *buf = (wchar_t *)calloc(bytes / sizeof(wchar_t) + 2, sizeof(wchar_t));
    if (!buf) return -1;
    DWORD got = bytes;
    if (RegGetValueW(HKEY_CURRENT_USER, L"Environment", L"Path", fl, &t, buf, &got) != ERROR_SUCCESS) {
        free(buf);
        return -1;
    }
    *out = buf;
    *type = t;
    return 1;
}

static void write_user_path(const wchar_t *v, DWORD type) {
    RegSetKeyValueW(HKEY_CURRENT_USER, L"Environment", L"Path", type ? type : REG_EXPAND_SZ, v,
                    (DWORD)((wcslen(v) + 1) * sizeof(wchar_t)));
    SendMessageTimeoutW(HWND_BROADCAST, WM_SETTINGCHANGE, 0, (LPARAM)L"Environment", SMTO_ABORTIFHUNG, 2000, NULL);
}

/* exact entry comparison: case-insensitive, trailing backslash ignored */
static int same_dir(const wchar_t *entry, size_t n, const wchar_t *dir) {
    while (n && (entry[0] == L' ')) { entry++; n--; }
    while (n && (entry[n - 1] == L'\\' || entry[n - 1] == L' ')) n--;
    size_t m = wcslen(dir);
    return n == m && _wcsnicmp(entry, dir, n) == 0;
}

static int path_has(const wchar_t *path, const wchar_t *dir) {
    const wchar_t *p = path;
    while (*p) {
        const wchar_t *e = wcschr(p, L';');
        size_t n = e ? (size_t)(e - p) : wcslen(p);
        if (same_dir(p, n, dir)) return 1;
        if (!e) break;
        p = e + 1;
    }
    return 0;
}

static void add_to_user_path(void) {
    wchar_t *cur = NULL;
    DWORD type = REG_EXPAND_SZ;
    int rc = read_user_path(&cur, &type);
    if (rc < 0) return; /* could not read it whole: never risk overwriting */
    if (rc == 1 && path_has(cur, g_install)) { free(cur); return; }
    size_t need = (rc == 1 ? wcslen(cur) : 0) + wcslen(g_install) + 2;
    if (need > PATH_LIMIT) { free(cur); return; }
    wchar_t *next = (wchar_t *)calloc(need + 1, sizeof(wchar_t));
    if (!next) { free(cur); return; }
    if (rc == 1 && cur[0]) {
        size_t L = wcslen(cur);
        _snwprintf(next, need + 1, (L && cur[L - 1] == L';') ? L"%ls%ls" : L"%ls;%ls", cur, g_install);
    } else {
        wcscpy(next, g_install);
    }
    write_user_path(next, type);
    free(next);
    free(cur);
}

static void remove_from_user_path(void) {
    wchar_t *cur = NULL;
    DWORD type = REG_EXPAND_SZ;
    if (read_user_path(&cur, &type) != 1) return;
    wchar_t *next = (wchar_t *)calloc(wcslen(cur) + 2, sizeof(wchar_t));
    if (!next) { free(cur); return; }
    int removed = 0;
    const wchar_t *p = cur;
    while (1) {
        const wchar_t *e = wcschr(p, L';');
        size_t n = e ? (size_t)(e - p) : wcslen(p);
        if (same_dir(p, n, g_install)) {
            removed = 1;
        } else if (n) {
            if (next[0]) wcscat(next, L";");
            wcsncat(next, p, n);
        }
        if (!e) break;
        p = e + 1;
    }
    if (removed) write_user_path(next, type);
    free(next);
    free(cur);
}

/* ---------------------------------------------------------- shortcuts -- */
static void make_link(const wchar_t *lnk, const wchar_t *target, const wchar_t *args,
                      const wchar_t *workdir, const wchar_t *desc, const wchar_t *icon) {
    IShellLinkW *sl = NULL;
    if (FAILED(CoCreateInstance(&CLSID_ShellLink, NULL, CLSCTX_INPROC_SERVER, &IID_IShellLinkW, (void **)&sl)))
        return;
    sl->lpVtbl->SetPath(sl, target);
    if (args) sl->lpVtbl->SetArguments(sl, args);
    if (workdir) sl->lpVtbl->SetWorkingDirectory(sl, workdir);
    if (desc) sl->lpVtbl->SetDescription(sl, desc);
    if (icon) sl->lpVtbl->SetIconLocation(sl, icon, 0);
    IPersistFile *pf = NULL;
    if (SUCCEEDED(sl->lpVtbl->QueryInterface(sl, &IID_IPersistFile, (void **)&pf))) {
        pf->lpVtbl->Save(pf, lnk, TRUE);
        pf->lpVtbl->Release(pf);
    }
    sl->lpVtbl->Release(sl);
}

static int folder_link(int csidl, const wchar_t *name, wchar_t *out) {
    wchar_t dir[MAX_PATH];
    if (FAILED(SHGetFolderPathW(NULL, csidl, NULL, 0, dir))) return 0;
    _snwprintf(out, PATHMAX, L"%ls\\%ls", dir, name);
    return 1;
}

static void create_shortcuts(int desktop) {
    wchar_t lnk[PATHMAX];
    /* "opngx.lnk" was the CLI in v2.0.x; overwriting it fixes old installs */
    if (folder_link(CSIDL_PROGRAMS, L"opngx.lnk", lnk))
        make_link(lnk, g_studio, NULL, g_install, L"opngx studio - Optronis footage extraction and analysis", g_studio);
    if (folder_link(CSIDL_PROGRAMS, L"opngx engine (command line).lnk", lnk))
        make_link(lnk, L"cmd.exe", L"/K opngx-engine --help", g_install, L"opngx command-line engine", g_engine);
    if (desktop && folder_link(CSIDL_DESKTOPDIRECTORY, L"opngx.lnk", lnk))
        make_link(lnk, g_studio, NULL, g_install, L"opngx studio", g_studio);
}

static void delete_shortcuts(void) {
    wchar_t lnk[PATHMAX];
    if (folder_link(CSIDL_PROGRAMS, L"opngx.lnk", lnk)) DeleteFileW(lnk);
    if (folder_link(CSIDL_PROGRAMS, L"opngx engine (command line).lnk", lnk)) DeleteFileW(lnk);
    if (folder_link(CSIDL_DESKTOPDIRECTORY, L"opngx.lnk", lnk)) DeleteFileW(lnk);
}

/* --------------------------------------------------------------- docs -- */
static void install_docs(void) {
    CreateDirectoryW(g_docs, NULL);
    wchar_t zip[PATHMAX];
    _snwprintf(zip, PATHMAX, L"%ls\\docs.zip", g_docs);
    if (extract_rc(RES_DOCS, zip)) return;
    /* PowerShell single-quoted literals: a ' in a path is written as '' */
    wchar_t qz[2 * PATHMAX], qd[2 * PATHMAX];
    size_t a = 0, b = 0;
    for (const wchar_t *s = zip; *s && a < 2 * PATHMAX - 2; s++) { if (*s == L'\'') qz[a++] = L'\''; qz[a++] = *s; }
    qz[a] = 0;
    for (const wchar_t *s = g_docs; *s && b < 2 * PATHMAX - 2; s++) { if (*s == L'\'') qd[b++] = L'\''; qd[b++] = *s; }
    qd[b] = 0;
    wchar_t cmd[6 * PATHMAX];
    _snwprintf(cmd, 6 * PATHMAX,
               L"powershell -NoProfile -NonInteractive -WindowStyle Hidden -Command "
               L"\"Expand-Archive -Force -LiteralPath '%ls' -DestinationPath '%ls'\"", qz, qd);
    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof si);
    ZeroMemory(&pi, sizeof pi);
    si.cb = sizeof si;
    if (CreateProcessW(NULL, cmd, NULL, NULL, FALSE, CREATE_NO_WINDOW, NULL, g_install, &si, &pi)) {
        WaitForSingleObject(pi.hProcess, 120000);
        CloseHandle(pi.hThread);
        CloseHandle(pi.hProcess);
    }
    DeleteFileW(zip);
}

/* ---------------------------------------------------------- uninstall -- */
static int run_uninstall(void) {
    if (!g_silent &&
        MessageBoxW(NULL, L"Remove opngx (studio, engine, docs and shortcuts) from this computer?\n\n"
                          L"Your extracted frames, analysis results and your own modules/docs "
                          L"(in %APPDATA%\\opngx) are kept.",
                    L"Uninstall opngx", MB_OKCANCEL | MB_ICONQUESTION) != IDOK)
        return 1;
    if (!ensure_not_running(L"uninstall")) return 3;
    delete_shortcuts();
    remove_from_user_path();
    RegDeleteTreeW(HKEY_CURRENT_USER, UNINST_KEY);
    DeleteFileW(g_studio);
    DeleteFileW(g_engine);
    delete_tree(g_docs);

    /* we may BE g_uninst: a running exe cannot delete itself, so a hidden
     * cmd waits for us to exit, then removes uninstall.exe and the folder */
    wchar_t self[PATHMAX];
    GetModuleFileNameW(NULL, self, PATHMAX);
    if (_wcsicmp(self, g_uninst) == 0) {
        wchar_t cmd[3 * PATHMAX];
        _snwprintf(cmd, 3 * PATHMAX,
                   L"cmd.exe /C ping -n 3 127.0.0.1 >NUL & del /F /Q \"%ls\" & rmdir /S /Q \"%ls\"",
                   g_uninst, g_install);
        STARTUPINFOW si;
        PROCESS_INFORMATION pi;
        ZeroMemory(&si, sizeof si);
        ZeroMemory(&pi, sizeof pi);
        si.cb = sizeof si;
        if (CreateProcessW(NULL, cmd, NULL, NULL, FALSE, CREATE_NO_WINDOW, NULL, NULL, &si, &pi)) {
            CloseHandle(pi.hThread);
            CloseHandle(pi.hProcess);
        }
    } else {
        DeleteFileW(g_uninst);
        delete_tree(g_install);
    }
    ask(L"opngx has been removed.", L"Uninstall opngx", MB_OK | MB_ICONINFORMATION);
    return 0;
}

/* --------------------------------------------------------------- main -- */
static int install(int desktop) {
    if (!ensure_not_running(L"install")) return 3;
    CreateDirectoryW(g_install, NULL);
    int rc = extract_rc(RES_ENGINE, g_engine);
    if (!rc) rc = extract_rc(RES_STUDIO, g_studio);
    if (rc) {
        wchar_t msg[256];
        _snwprintf(msg, 256, L"Could not write the program files (code %d).\n\n%ls", rc,
                   rc == -2 ? L"Is opngx still running, or is the folder read-only?" : L"");
        ask(msg, L"opngx setup", MB_OK | MB_ICONERROR);
        return 1;
    }
    /* the uninstaller is this very program */
    wchar_t self[PATHMAX];
    GetModuleFileNameW(NULL, self, PATHMAX);
    if (_wcsicmp(self, g_uninst) != 0) CopyFileW(self, g_uninst, FALSE);
    install_docs();
    register_uninstall();
    add_to_user_path();
    create_shortcuts(desktop);
    return 0;
}

int WINAPI wWinMain(HINSTANCE hInst, HINSTANCE hPrev, LPWSTR cmdline, int show) {
    (void)hInst; (void)hPrev; (void)cmdline; (void)show;
    build_paths();
    int argc = 0, uninstall = 0;
    LPWSTR *argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    for (int i = 1; argv && i < argc; i++) {
        if (!_wcsicmp(argv[i], L"/S") || !_wcsicmp(argv[i], L"/silent") || !_wcsicmp(argv[i], L"--silent"))
            g_silent = 1;
        else if (!_wcsicmp(argv[i], L"--uninstall") || !_wcsicmp(argv[i], L"/uninstall"))
            uninstall = 1;
    }
    if (argv) LocalFree(argv);
    CoInitializeEx(NULL, COINIT_APARTMENTTHREADED);
    int rc;
    if (uninstall) {
        rc = run_uninstall();
    } else if (g_silent) {
        rc = install(0);
    } else {
        if (MessageBoxW(NULL,
                        L"opngx " APP_VERSION_W L"\n\n"
                        L"Pixel-exact extraction, video export and analysis for Optronis "
                        L"high-speed-camera recordings.\n\n"
                        L"This installs, for your user only (no admin rights needed):\n"
                        L"  - the opngx studio (Start-menu shortcut)\n"
                        L"  - the opngx-engine command-line tool (added to your PATH)\n"
                        L"  - the documentation and an uninstaller\n\n"
                        L"Continue?",
                        L"Install opngx", MB_OKCANCEL | MB_ICONINFORMATION) != IDOK) {
            CoUninitialize();
            return 0;
        }
        int desktop = MessageBoxW(NULL, L"Create a desktop shortcut too?", L"opngx", MB_YESNO | MB_ICONQUESTION) == IDYES;
        rc = install(desktop);
        if (!rc) {
            wchar_t done[2 * PATHMAX];
            _snwprintf(done, 2 * PATHMAX,
                       L"opngx " APP_VERSION_W L" is installed.\n\n"
                       L"Start it from the Start menu: opngx.\n\n"
                       L"Command line (in a NEW terminal): opngx-engine --help\n\n"
                       L"Installed to:\n  %ls\n\nRemove it any time from Settings > Apps.",
                       g_install);
            MessageBoxW(NULL, done, L"opngx setup", MB_OK | MB_ICONINFORMATION);
        }
    }
    CoUninitialize();
    return rc;
}
