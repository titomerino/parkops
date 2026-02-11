def minutes_to_hours_and_minutes(total_minutes: int):
    hours = total_minutes // 60
    minutes = total_minutes % 60

    return hours, f"{minutes:02d}"