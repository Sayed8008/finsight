# Sharing FinSight

How to build a copy of FinSight somebody else can run without installing
Python, creating a virtual environment or opening a terminal.

**They will still need MySQL.** That is not a packaging shortcut left untaken:
the analytics layer depends on MySQL's date functions and `GROUP BY` semantics,
and SQLite was rejected for that reason (ADR-005). Bundling removes Python, the
virtual environment and the two-terminal launch. It does not remove the
database.

---

## Building it

```bash
.venv/bin/pip install pyinstaller
.venv/bin/pyinstaller packaging/finsight.spec --noconfirm
```

The result is `dist/FinSight/` — one executable and its libraries. Zip that
folder and send it:

```bash
cd dist && zip -r FinSight-linux.zip FinSight
```

A folder rather than a single file on purpose. `--onefile` has to unpack
several hundred megabytes to a temporary directory on *every* launch, which
turns a double-click into a visible wait; the folder starts immediately.

**Build on the system you are shipping to.** PyInstaller freezes the
interpreter and libraries of the machine it runs on, so a Linux build does not
run on Windows or macOS and cannot be converted into one.

For Windows, that is what `.github/workflows/windows-build.yml` is for — see
below — so no Windows development machine is needed.

---

## Windows

Built on a GitHub Actions `windows-latest` runner:

1. **Actions** tab → **Windows build** → **Run workflow** (or push a `v*` tag,
   or `gh workflow run "Windows build"`).
2. When it finishes, open the run and download the **`FinSight-windows-x86_64`**
   artifact. It is kept for 30 days.

The artifact is a ZIP containing `FinSight.exe`, its libraries and
`SETUP.txt` — the Windows instructions from `packaging/SETUP-windows.txt`.

Two things are platform-specific and nothing else is:

* **The icon.** PyInstaller refuses an SVG on Windows; the executable needs a
  `.ico`. `make_icon.py` renders one from the same SVG the application uses, so
  the two cannot drift. The workflow regenerates it on every build.
* **The setup guide.** Windows needs different words, not translated ones:
  MySQL is an installer with a service and an authentication mode to choose,
  Notepad will save `.env` as `.env.txt` unless told otherwise, and SmartScreen
  interrupts an unsigned executable in a way that looks like a virus warning.

**SmartScreen.** The executable is not code-signed, so the first launch shows
"Windows protected your PC". Users click *More info* → *Run anyway*. Signing
requires a paid certificate; the setup guide explains the warning rather than
leaving somebody to assume the file is malicious.

---

## What your friend has to do

**1. Install MySQL 8** and make sure it is running.

**2. Create the database and a user for it.** From a MySQL prompt:

```sql
CREATE DATABASE finsight CHARACTER SET utf8mb4;
CREATE USER 'finsight'@'localhost' IDENTIFIED BY 'a-password-they-choose';
GRANT ALL PRIVILEGES ON finsight.* TO 'finsight'@'localhost';
FLUSH PRIVILEGES;
```

**3. Put a `.env` beside the FinSight executable**, containing:

```
SECRET_KEY=<a long random string of their own>
DATABASE_URL=mysql+pymysql://finsight:a-password-they-choose@localhost:3306/finsight
```

A key can be generated anywhere Python is available, or with
`openssl rand -base64 48`.

**4. Run FinSight.** The first launch creates the tables it needs.

If anything is wrong — no `.env`, MySQL not running, the wrong password — it
says so in a dialog naming the file it looked for, rather than closing without
explanation.

---

## Never ship these

**Your `.env`.** It contains your `SECRET_KEY` and your database password.
Everyone who received a copy would have both. It is gitignored for that reason,
and the spec file deliberately does not bundle it — each person writes their
own.

**Your `.venv`.** 780 MB, and full of absolute paths to your machine.

**Your database.** It is your own financial records.

---

## The alternative, for technical friends

The repository is public. Someone comfortable with a terminal is better served
by it than by a zip file, and gets updates with `git pull`:

<https://github.com/Sayed8008/finsight>

`README.md` covers the setup, and `scripts/install-desktop-entry.sh` gives them
the same application-menu entry.
