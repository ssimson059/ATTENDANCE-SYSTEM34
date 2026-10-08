"""Send fee-due reminders (run once a day from cron / Windows Task Scheduler).

    python send_reminders.py

Safe to run repeatedly - every reminder is sent only once.  Channels / schedule: see .env.example.
"""
import app as A
import features


def main():
    A.bootstrap()
    with A.app.app_context():
        print(features.run_reminders("cron"))


if __name__ == "__main__":
    main()
