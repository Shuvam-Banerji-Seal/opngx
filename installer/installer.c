/* installer.c — one-click Windows setup for opngx.
 *
 * Flow: welcome → (optional desktop shortcut) → extract payload →
 *       registry (uninstall entry + user PATH) → Start-Menu shortcut → done.
 *
 * The engine binary is embedded as RCDATA resource #101 by windres.
 * Everything is per-user (%LOCALAPDATA%), so no admin rights are needed.
 *
 * Build (MinGW):
 *   x86_64-w64-mingw32-windres app.rc apprc.o
 *   x86_64-w64-mingw32-gcc -O2 -mwindows installer.c apprc.o -o opngx-setup.exe \
 *       -lole32 -luuid -lshell32 -ladvapi32 -static
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <shlobj.h>
#include <shellapi.h>
#include <stdio.h>
#include <string.h>

#define RES_ENGINE 101
#define APP_VERSION "1.2.0"
#define APP_NAME    "opngx"
#define PUBLISHER   "opngx contributors"

static char g_install[MAX_PATH];      /* e.g. C:\Users\x\AppData\Local\opngx */
static char g_engine_path[MAX_PATH];

static void build_paths(void) {
    char base[MAX_PATH];
    if (!SUCCEEDED(SHGetFolderPathA(NULL, CSIDL_LOCAL_APPDATA, NULL, 0, base)))
        strcpy(base, "C:\\");
    snprintf(g_install, sizeof g_install, "%s\\%s", base, APP_NAME);
    snprintf(g_engine_path, sizeof g_engine_path, "%s\\opngx-engine.exe",
             g_install);
}

static int write_payload(void) {
    HRSRC hr = FindResourceA(NULL, MAKEINTRESOURCEA(RES_ENGINE), RT_RCDATA);
    if (!hr) return -1;
    HGLOBAL hg = LoadResource(NULL, hr);
    if (!hg) return -1;
    const void *data = LockResource(hg);
    DWORD size = SizeofResource(NULL, hr);
    if (!data || !size) return -1;

    CreateDirectoryA(g_install, NULL);
    HANDLE fh = CreateFileA(g_engine_path, GENERIC_WRITE, 0, NULL,
                            CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (fh == INVALID_HANDLE_VALUE) return -2;
    DWORD off = 0;
    while (off < size) {
        DWORD written = 0;
        if (!WriteFile(fh, (const char *)data + off, size - off, &written,
                       NULL) || !written) { CloseHandle(fh); return -3; }
        off += written;
    }
    CloseHandle(fh);
    return 0;
}

/* ------------------------- registry helpers ------------------------ */
static void set_reg(HKEY root, const char *key, const char *name,
                    const char *value) {
    HKEY h;
    if (RegCreateKeyExA(root, key, 0, NULL, 0, KEY_SET_VALUE, NULL,
                        &h, NULL) != ERROR_SUCCESS) return;
    RegSetValueExA(h, name, 0, REG_SZ, (const BYTE *)value,
                   (DWORD)(strlen(value) + 1));
    RegCloseKey(h);
}

static void register_uninstall(void) {
    char key[512];
    snprintf(key, sizeof key,
             "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\%s",
             APP_NAME);

    char uninstall[1200];
    snprintf(uninstall, sizeof uninstall,
             "\"%s\" --uninstall", g_engine_path);

    set_reg(HKEY_CURRENT_USER, key, "DisplayName", APP_NAME);
    set_reg(HKEY_CURRENT_USER, key, "DisplayVersion", APP_VERSION);
    set_reg(HKEY_CURRENT_USER, key, "Publisher", PUBLISHER);
    set_reg(HKEY_CURRENT_USER, key, "InstallLocation", g_install);
    set_reg(HKEY_CURRENT_USER, key, "DisplayIcon", g_engine_path);
    set_reg(HKEY_CURRENT_USER, key, "UninstallString", uninstall);
    set_reg(HKEY_CURRENT_USER, key, "NoModify", "1");
    set_reg(HKEY_CURRENT_USER, key, "NoRepair", "1");
    set_reg(HKEY_CURRENT_USER, key, "HelpLink",
            "https://github.com/Shuvam-Banerji-Seal/opngx");

    /* EstimatedSize in KiB */
    HANDLE fh = CreateFileA(g_engine_path, GENERIC_READ, FILE_SHARE_READ,
                            NULL, OPEN_EXISTING, 0, NULL);
    if (fh != INVALID_HANDLE_VALUE) {
        LARGE_INTEGER sz;
        if (GetFileSizeEx(fh, &sz)) {
            char kib[32];
            DWORD v = (DWORD)(sz.QuadPart / 1024);
            snprintf(kib, sizeof kib, "%lu", (unsigned long)v);
            HKEY h;
            if (RegCreateKeyExA(HKEY_CURRENT_USER, key, 0, NULL, 0,
                                KEY_SET_VALUE, NULL, &h, NULL) == ERROR_SUCCESS) {
                RegSetValueExA(h, "EstimatedSize", 0, REG_DWORD,
                               (const BYTE *)&v, sizeof v);
                RegCloseKey(h);
            }
        }
        CloseHandle(fh);
    }
}

static void add_to_user_path(void) {
    const char *needle = "\\opngx";
    char cur[4096] = "";
    DWORD sz = sizeof cur;
    HKEY h;
    if (RegOpenKeyExA(HKEY_CURRENT_USER, "Environment", 0,
                      KEY_QUERY_VALUE, &h) == ERROR_SUCCESS) {
        DWORD type = 0;
        RegQueryValueExA(h, "Path", NULL, &type, (BYTE *)cur, &sz);
        RegCloseKey(h);
    }
    if (strstr(cur, needle)) return;               /* already present */
    char next[4600];
    if (cur[0]) snprintf(next, sizeof next, "%s;%s", cur, g_install);
    else        snprintf(next, sizeof next, "%s", g_install);
    if (RegOpenKeyExA(HKEY_CURRENT_USER, "Environment", 0,
                      KEY_SET_VALUE, &h) == ERROR_SUCCESS) {
        RegSetValueExA(h, "Path", 0, REG_EXPAND_SZ, (const BYTE *)next,
                       (DWORD)(strlen(next) + 1));
        RegCloseKey(h);
        /* tell running apps the environment changed */
        SendMessageTimeoutA(HWND_BROADCAST, WM_SETTINGCHANGE, 0,
                            (LPARAM) "Environment", SMTO_ABORTIFHUNG,
                            2000, NULL);
    }
}

/* --------------------------- shortcuts ----------------------------- */
static void make_shortcut(const wchar_t *link_path) {
    CoInitializeEx(NULL, COINIT_APARTMENTTHREADED);
    IShellLinkW *sl = NULL;
    if (FAILED(CoCreateInstance(&CLSID_ShellLink, NULL, CLSCTX_INPROC_SERVER,
                                &IID_IShellLinkW, (void **)&sl))) return;
    wchar_t wpath[MAX_PATH];
    MultiByteToWideChar(CP_UTF8, 0, g_engine_path, -1, wpath, MAX_PATH);
    sl->lpVtbl->SetPath(sl, wpath);
    sl->lpVtbl->SetDescription(sl, L"Optronis .bin footage extractor");
    IPersistFile *pf = NULL;
    if (SUCCEEDED(sl->lpVtbl->QueryInterface(sl, &IID_IPersistFile,
                                             (void **)&pf))) {
        pf->lpVtbl->Save(pf, link_path, TRUE);
        pf->lpVtbl->Release(pf);
    }
    sl->lpVtbl->Release(sl);
    CoUninitialize();
}

static void start_menu_shortcut(void) {
    wchar_t dir[MAX_PATH];
    if (FAILED(SHGetFolderPathW(NULL, CSIDL_PROGRAMS, NULL, 0, dir))) return;
    wcscat(dir, L"\\opngx.lnk");
    make_shortcut(dir);
}

static void desktop_shortcut(void) {
    wchar_t dir[MAX_PATH];
    if (FAILED(SHGetFolderPathW(NULL, CSIDL_DESKTOPDIRECTORY, NULL, 0, dir)))
        return;
    wcscat(dir, L"\\opngx.lnk");
    make_shortcut(dir);
}

/* ---------------------------- uninstall ---------------------------- */
static int run_uninstall(void) {
    /* best effort: remove files, shortcuts, PATH entry, registry */
    DeleteFileA(g_engine_path);
    RemoveDirectoryA(g_install);

    wchar_t dir[MAX_PATH];
    if (SUCCEEDED(SHGetFolderPathW(NULL, CSIDL_PROGRAMS, NULL, 0, dir))) {
        wcscat(dir, L"\\opngx.lnk"); DeleteFileW(dir);
    }
    if (SUCCEEDED(SHGetFolderPathW(NULL, CSIDL_DESKTOPDIRECTORY, NULL, 0, dir))) {
        wcscat(dir, L"\\opngx.lnk"); DeleteFileW(dir);
    }

    char key[512];
    snprintf(key, sizeof key,
             "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\%s",
             APP_NAME);
    RegDeleteTreeA(HKEY_CURRENT_USER, key);

    /* strip ourselves from PATH */
    char cur[4096] = "";
    DWORD sz = sizeof cur;
    HKEY h;
    if (RegOpenKeyExA(HKEY_CURRENT_USER, "Environment", 0,
                      KEY_QUERY_VALUE, &h) == ERROR_SUCCESS) {
        RegQueryValueExA(h, "Path", NULL, NULL, (BYTE *)cur, &sz);
        RegCloseKey(h);
        char next[4096] = "";
        char *tok = strtok(cur, ";");
        int first = 1;
        while (tok) {
            if (!strstr(tok, "\\opngx")) {
                if (!first) strncat(next, ";", sizeof next - strlen(next) - 1);
                strncat(next, tok, sizeof next - strlen(next) - 1);
                first = 0;
            }
            tok = strtok(NULL, ";");
        }
        if (RegOpenKeyExA(HKEY_CURRENT_USER, "Environment", 0,
                          KEY_SET_VALUE, &h) == ERROR_SUCCESS) {
            RegSetValueExA(h, "Path", 0, REG_EXPAND_SZ, (const BYTE *)next,
                           (DWORD)(strlen(next) + 1));
            RegCloseKey(h);
        }
    }
    MessageBoxA(NULL, "opngx has been removed.", "Uninstall",
                MB_OK | MB_ICONINFORMATION);
    return 0;
}

/* ------------------------------- main ------------------------------ */
int WINAPI WinMain(HINSTANCE hInst, HINSTANCE hPrev, LPSTR cmd, int show) {
    (void)hInst; (void)hPrev; (void)cmd; (void)show;
    build_paths();

    int silent = GetCommandLineA() &&
                 (strstr(GetCommandLineA(), "/S") ||
                  strstr(GetCommandLineA(), "/silent"));

    if (GetCommandLineA() && strstr(GetCommandLineA(), "--uninstall"))
        return run_uninstall();

    if (silent) {
        /* scripted install: user dir shortcut only */
        int rc = write_payload();
        if (rc) return 1;
        register_uninstall();
        add_to_user_path();
        start_menu_shortcut();
        return 0;
    }

    if (MessageBoxA(NULL,
        "opngx " APP_VERSION "\n\n"
        "Fast, pixel-exact Optronis .bin \xE2\x86\x92 PNG extractor.\n\n"
        "This will:\n"
        "  1. Install the command-line engine to your user folder\n"
        "     (no admin rights needed)\n"
        "  2. Add it to your PATH so 'opngx-engine' works anywhere\n"
        "  3. Create a Start Menu shortcut\n\n"
        "Also create a desktop shortcut?",
        "Install opngx", MB_YESNO | MB_ICONINFORMATION) != IDYES)
        return 0;

    int want_desktop =
        (MessageBoxA(NULL, "Create a desktop shortcut too?", "opngx",
                     MB_YESNO | MB_ICONQUESTION) == IDYES);

    /* extract */
    int rc = write_payload();
    if (rc) {
        char msg[128];
        snprintf(msg, sizeof msg, "Payload extraction failed (code %d).", rc);
        MessageBoxA(NULL, msg, "opngx installer", MB_OK | MB_ICONERROR);
        return 1;
    }

    register_uninstall();
    add_to_user_path();
    start_menu_shortcut();
    if (want_desktop) desktop_shortcut();

    char done[1024];
    snprintf(done, sizeof done,
        "opngx " APP_VERSION " installed successfully!\n\n"
        "Installed to:\n  %s\n\n"
        "Try it in a NEW terminal window:\n"
        "  opngx-engine info\n"
        "  opngx-engine batch D:\\footage -o D:\\frames -j 0\n\n"
        "(GUI + Python tools ship separately via 'pip install ./python')",
        g_install);
    MessageBoxA(NULL, done, "opngx installer", MB_OK | MB_ICONINFORMATION);
    return 0;
}
