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

**Build on the system you are shipping to.** A Linux build does not run on
Windows or macOS. There is no cross-compilation — building a Windows copy means
running the same command on Windows.

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
