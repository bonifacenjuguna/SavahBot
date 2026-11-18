# Weather guide

Open **Manage > Weather** (shortcut `w`). Weather comes from [Open-Meteo](https://open-meteo.com/) through your SavahBot server. **No API key is needed**, and there is no `WEATHER_API_KEY` any more.

## What you get
- **Dashboard**: current conditions (temperature, feels-like, humidity, wind and gusts, pressure, cloud, visibility, rain), the next 12 to 72 hours, 3 to 14 days, sunrise and sunset, and when the data was fetched. Old data is clearly marked when Open-Meteo cannot be reached.
- **Places**: search by name, add coordinates, or press **Use this device's location**. The browser asks permission only when you press that button; the position is rounded to about 1 km before it is saved. Several places, one default, rename, remove.
- **Settings** (Weather settings): units (°C/°F, km/h, m/s, mph, kn, mm/in), 12/24-hour clock, hours and days shown, which sections show, refresh interval, alert rules.
- **Alerts** through the Notification Centre (see NOTIFICATIONS.md): rain likely, heavy rain, very hot, very cold, strong gusts, thunderstorm, plus an optional morning summary. Quiet hours, pause, push, bell and Telegram all apply. Each alert category can be switched per channel on the Notifications page.
- **Telegram**: `/weather [place]`, `/forecast [place]`, `/hourly [place]`, `/locations [number]`. Without a place they use your default.

## How it works
Browser and Telegram never call Open-Meteo. Everything goes through `WeatherService`:
1. Forecasts are cached for 15 minutes (memory, plus Redis when you run it). Several requests at once share one provider call.
2. If Open-Meteo fails, a cached forecast up to 12 hours old is shown with a visible "old data" notice. If there is none, you get a plain error. Alerts never use old data.
3. Failures are retried with growing pauses (default 2 retries); repeated failures pause calls for a while; a "too many requests" answer waits several minutes. The Refresh button is limited to one real call per minute per place.
4. Forecasts are stored in cache only, never permanently. Saved places, preferences, rules and alert state are in the database. Coordinates are kept out of the logs.
5. Data is stored in metric units and converted for display, so changing units never needs a new request.

## Alert rules
A rule is: *variable* *comparison* *value*, *within the next N hours*, for a place (default or specific), with a notification category, a check interval (15 min or more), a cooldown, and an optional active time window. Variables: chance of rain, rain amount, highest temperature, lowest temperature, wind speed, wind gusts, thunderstorm. Values are typed in your chosen units.

No spam: a rule sends once when its condition starts, stays quiet while it continues, re-arms when the condition ends, and only repeats for a *later* episode after the cooldown. Edited rules start fresh. Alerts say they are SavahBot's reading of the forecast, **not official weather warnings**: rely on your national weather service for safety decisions.

## Limits and licence
- Free Open-Meteo use is **non-commercial** only, and asks for attribution (CC BY 4.0). SavahBot shows "Weather data by Open-Meteo.com" with a link. If you run SavahBot commercially (ads, subscriptions, a business), you need an Open-Meteo commercial plan; put its key in `WEATHER_COMMERCIAL_API_KEY` and SavahBot switches to the paid endpoints automatically. Only Open-Meteo's own fixed addresses are ever called; there is no custom-URL setting.
- Open-Meteo's free allowance (at time of writing 600 calls per minute, 5,000 per hour, 10,000 per day) is far above what SavahBot uses: about two calls an hour per monitored place.
- Forecasts are forecasts. Accuracy varies by place and Open-Meteo's models.
- Place search quality depends on Open-Meteo's geocoding; small villages may need coordinates.

## Settings in `.env.example`
`WEATHER_COMMERCIAL_API_KEY` (blank), `WEATHER_FORECAST_TTL_MINUTES`, `WEATHER_STALE_MAX_HOURS`, `WEATHER_GEOCODE_TTL_HOURS`, `WEATHER_TIMEOUT_SECONDS`, `WEATHER_RETRIES`.

## For developers
`backend/app/weather/`: `provider.py` (interface + Open-Meteo + normalization), `codes.py` (WMO codes), `units.py`, `rules.py` (reusable evaluator), `service.py`, `format.py` (Telegram). Add a provider by implementing `search()` and `forecast()` and returning `normalize_forecast`'s shape. API: `/api/weather/*`.
