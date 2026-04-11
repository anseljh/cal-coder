import sys

from cal_coder.pipeline import run_backlog_load, run_daily_update


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "daily":
        day_arg = sys.argv[2] if len(sys.argv) > 2 else None
        run_daily_update(day_arg)
    else:
        run_backlog_load()


if __name__ == "__main__":
    main()
