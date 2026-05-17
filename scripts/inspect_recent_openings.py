import sqlite3


def main() -> None:
    conn = sqlite3.connect("crypto_ai_trader.db")
    cur = conn.cursor()

    print("recent_opened_and_confirmed:")
    rows = cur.execute(
        """
        select created_at, event_type, symbol, trade_id
        from tradejournalrecord
        where event_type in ('trade_opened', 'trade_confirmed')
        order by created_at desc
        limit 30
        """
    ).fetchall()
    for row in rows:
        print(row)

    print("current_trade_rows_by_symbol_status:")
    rows = cur.execute(
        """
        select symbol, status, count(1)
        from simtraderecord
        group by symbol, status
        order by symbol, status
        """
    ).fetchall()
    for row in rows:
        print(row)

    print("opened_count_by_symbol:")
    rows = cur.execute(
        """
        select symbol, count(1)
        from tradejournalrecord
        where event_type = 'trade_opened'
        group by symbol
        order by count(1) desc, symbol
        """
    ).fetchall()
    for row in rows:
        print(row)

    conn.close()


if __name__ == "__main__":
    main()
