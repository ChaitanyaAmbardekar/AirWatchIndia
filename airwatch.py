import tkinter as tk
from tkinter import messagebox
import requests
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import seaborn as sns
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from datetime import datetime
import time
import threading

OWM_KEY = "45a8fae89922cdeae3f472a2a477c2cb"


BG      = "#0f1117"
CARD    = "#1c1f2e"
BORDER  = "#2e3348"
GREEN   = "#4cf0b4"
TEXT    = "#e8ecf4"
SUBTEXT = "#888888"

def pm25_to_aqi(pm):
    breakpoints = [
        (0.0,   12.0,   0,   50),
        (12.1,  35.4,  51,  100),
        (35.5,  55.4, 101,  150),
        (55.5, 150.4, 151,  200),
        (150.5,250.4, 201,  300),
        (250.5, 500.4,301,  500),
    ]
    for c_low, c_high, aqi_low, aqi_high in breakpoints:
        if c_low <= pm <= c_high:
            return round(((aqi_high - aqi_low) /
                          (c_high - c_low)) * (pm - c_low) + aqi_low)
    return 500

def get_category(aqi):
    if aqi <= 50:  return "Good",                    "#4cf0b4"
    if aqi <= 100: return "Moderate",                "#f0d34c"
    if aqi <= 150: return "Unhealthy for Sensitive", "#f0934c"
    if aqi <= 200: return "Unhealthy",               "#e04c4c"
    return              "Very Unhealthy",            "#a855f7"

def get_mask(aqi):
    if aqi <= 50:  return "😊 No Mask Needed",           "Air is clean — go outside freely!",        "#4cf0b4"
    if aqi <= 100: return "🙂 Mask Optional",             "Acceptable. Sensitive: basic mask.",        "#f0d34c"
    if aqi <= 150: return "😷 Wear a Surgical Mask",      "Unhealthy for sensitive groups.",           "#f0934c"
    if aqi <= 200: return "😷 Wear an N95 Mask",          "Air is unhealthy. Avoid outdoor exercise.", "#e04c4c"
    return               "🚨 N95 Mandatory — HAZARDOUS", "Do NOT go outside. Keep windows shut.",     "#a855f7"


class AirWatchApp:
    def __init__(self, root):
        self.root = root
        self.root.title("🌿 AirWatch India")
        self.root.configure(bg=BG)
        self.root.geometry("960x900")
        self.root.minsize(800, 700)

        sns.set_style("darkgrid", {
            "axes.facecolor"  : CARD,
            "figure.facecolor": BG,
            "axes.edgecolor"  : BORDER,
            "grid.color"      : BORDER,
            "axes.labelcolor" : TEXT,
            "xtick.color"     : SUBTEXT,
            "ytick.color"     : SUBTEXT,
        })

        self._build_ui()

    def _build_ui(self):

        # TOP FIXED SECTION (never scrolls) 
        top = tk.Frame(self.root, bg=BG)
        top.pack(side="top", fill="x", padx=20, pady=(16, 0))

        # Title
        tk.Label(top, text="🌿 AirWatch India",
                 font=("Arial", 20, "bold"),
                 bg=BG, fg=GREEN).pack()
        tk.Label(top, text="Real-time Air Quality Monitor for Indian Cities",
                 font=("Arial", 9), bg=BG, fg=SUBTEXT).pack(pady=(2, 10))

        # Search row
        srow = tk.Frame(top, bg=BG)
        srow.pack()
        self.city_entry = tk.Entry(srow, font=("Arial", 12), width=26,
                                   bg=CARD, fg=SUBTEXT, insertbackground=TEXT,
                                   relief="flat", bd=6)
        self.city_entry.insert(0, "Enter city name…")
        self.city_entry.bind("<FocusIn>",  self._clear_ph)
        self.city_entry.bind("<FocusOut>", self._restore_ph)
        self.city_entry.bind("<Return>",   lambda e: self._start_fetch())
        self.city_entry.pack(side="left", padx=(0, 8))

        self.btn = tk.Button(srow, text="Check AQI →",
                             font=("Arial", 11, "bold"),
                             bg=GREEN, fg=BG, relief="flat",
                             padx=14, pady=5, cursor="hand2",
                             command=self._start_fetch)
        self.btn.pack(side="left")

        # Status
        self.status_var = tk.StringVar(value="")
        tk.Label(top, textvariable=self.status_var,
                 font=("Arial", 9), bg=BG, fg=SUBTEXT).pack(pady=(4, 0))

        # 3 INFO CARDS (fixed, below search) 
        cards_row = tk.Frame(self.root, bg=BG)
        cards_row.pack(fill="x", padx=20, pady=(10, 6))
        cards_row.columnconfigure(0, weight=1)
        cards_row.columnconfigure(1, weight=1)
        cards_row.columnconfigure(2, weight=1)

        # Card 1 — AQI
        c1 = self._card(cards_row)
        c1.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self._lbl(c1, "City & AQI", 9, SUBTEXT)
        self.city_lbl = self._lbl(c1, "—", 12, TEXT)
        self.aqi_lbl  = self._lbl(c1, "—", 30, TEXT, bold=True)
        self.cat_lbl  = self._lbl(c1, "—", 10, SUBTEXT)

        # Card 2 — Pollutants
        c2 = self._card(cards_row)
        c2.grid(row=0, column=1, sticky="nsew", padx=(0, 6))
        self._lbl(c2, "Pollutants (µg/m³)", 9, SUBTEXT)
        prow = tk.Frame(c2, bg=CARD)
        prow.pack(fill="x", pady=6)
        self.pm25_val = self._pill(prow, "PM2.5")
        self.pm10_val = self._pill(prow, "PM10")
        self.no2_val  = self._pill(prow, "NO₂")

        # Card 3 — Mask
        c3 = self._card(cards_row)
        c3.grid(row=0, column=2, sticky="nsew")
        self._lbl(c3, "Mask Recommendation", 9, SUBTEXT)
        self.mask_lbl = self._lbl(c3, "—", 11, TEXT, bold=True)
        self.mask_tip = self._lbl(c3, "", 8, SUBTEXT)

        # SCROLLABLE CHART AREA
        # Outer frame that holds canvas + scrollbar
        chart_container = tk.Frame(self.root, bg=BG)
        chart_container.pack(fill="both", expand=True, padx=20, pady=(4, 10))

        self.chart_canvas = tk.Canvas(chart_container, bg=BG,
                                      highlightthickness=0)
        scrollbar = tk.Scrollbar(chart_container, orient="vertical",
                                 command=self.chart_canvas.yview)
        self.chart_canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        self.chart_canvas.pack(side="left", fill="both", expand=True)

        # Inner frame that matplotlib embeds into
        self.chart_inner = tk.Frame(self.chart_canvas, bg=BG)
        self.chart_window = self.chart_canvas.create_window(
            (0, 0), window=self.chart_inner, anchor="nw"
        )

        self.chart_inner.bind("<Configure>", self._on_frame_resize)
        self.chart_canvas.bind("<Configure>", self._on_canvas_resize)

        # Mouse wheel scrolling
        self.chart_canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    # SCROLLBAR HELPERS 
    def _on_frame_resize(self, event):
        self.chart_canvas.configure(
            scrollregion=self.chart_canvas.bbox("all"))

    def _on_canvas_resize(self, event):
        self.chart_canvas.itemconfig(
            self.chart_window, width=event.width)

    def _on_mousewheel(self, event):
        self.chart_canvas.yview_scroll(int(-1*(event.delta/120)), "units")

    # WIDGET HELPERS 
    def _card(self, parent):
        f = tk.Frame(parent, bg=CARD,
                     highlightbackground=BORDER,
                     highlightthickness=1)
        f.configure(padx=12, pady=10)
        return f

    def _lbl(self, parent, text, size, color, bold=False):
        w = "bold" if bold else "normal"
        lbl = tk.Label(parent, text=text,
                       font=("Arial", size, w),
                       bg=CARD, fg=color, anchor="w",
                       wraplength=220)
        lbl.pack(anchor="w", pady=1)
        return lbl

    def _pill(self, parent, name):
        f = tk.Frame(parent, bg=CARD)
        f.pack(side="left", expand=True, padx=4)
        val = tk.Label(f, text="—", font=("Arial", 13, "bold"),
                       bg=CARD, fg=GREEN)
        val.pack()
        tk.Label(f, text=name, font=("Arial", 8),
                 bg=CARD, fg=SUBTEXT).pack()
        return val

    # PLACEHOLDER 
    def _clear_ph(self, e):
        if self.city_entry.get() == "Enter city name…":
            self.city_entry.delete(0, "end")
            self.city_entry.config(fg=TEXT)

    def _restore_ph(self, e):
        if not self.city_entry.get():
            self.city_entry.insert(0, "Enter city name…")
            self.city_entry.config(fg=SUBTEXT)

    # FETCH 
    def _start_fetch(self):
        city = self.city_entry.get().strip()
        if not city or city == "Enter city name…":
            messagebox.showwarning("Input", "Please enter a city name.")
            return
        self.btn.config(state="disabled", text="Loading…")
        self.status_var.set("⏳ Fetching live data…")
        threading.Thread(target=self._fetch_all,
                         args=(city,), daemon=True).start()

    def _fetch_all(self, city):
        try:
            # Geocoding
            geo = requests.get(
                f"http://api.openweathermap.org/geo/1.0/direct"
                f"?q={city},IN&limit=1&appid={OWM_KEY}", timeout=10
            ).json()
            if not geo:
                self.root.after(0, lambda: self._err("City not found! Try another."))
                return

            lat, lon = geo[0]['lat'], geo[0]['lon']
            cityname = geo[0]['name']

            # Current AQI
            cur  = requests.get(
                f"http://api.openweathermap.org/data/2.5/air_pollution"
                f"?lat={lat}&lon={lon}&appid={OWM_KEY}", timeout=10
            ).json()
            comp = cur['list'][0]['components']
            pm25 = comp.get('pm2_5', 0)
            pm10 = comp.get('pm10',  0)
            no2  = comp.get('no2',   0)
            aqi  = pm25_to_aqi(pm25)

            # 7-Day Historical
            et = int(time.time())
            st = et - (7 * 24 * 3600)
            hist = requests.get(
                f"http://api.openweathermap.org/data/2.5/air_pollution/history"
                f"?lat={lat}&lon={lon}&start={st}&end={et}&appid={OWM_KEY}",
                timeout=10
            ).json()
            wt, wa = [], []
            if 'list' in hist:
                step = max(1, len(hist['list']) // 7)
                for item in hist['list'][::step][:7]:
                    wt.append(datetime.fromtimestamp(item['dt']))
                    wa.append(pm25_to_aqi(item['components'].get('pm2_5', 0)))

            # 24hr Forecast
            fc = requests.get(
                f"http://api.openweathermap.org/data/2.5/air_pollution/forecast"
                f"?lat={lat}&lon={lon}&appid={OWM_KEY}", timeout=10
            ).json()
            ft = [datetime.now()]
            fa = [aqi]
            if 'list' in fc:
                for item in fc['list'][:23]:
                    ft.append(datetime.fromtimestamp(item['dt']))
                    fa.append(pm25_to_aqi(item['components'].get('pm2_5', 0)))

            self.root.after(0, lambda: self._update(
                cityname, aqi, pm25, pm10, no2, wt, wa, ft, fa))

        except Exception as ex:
            self.root.after(0, lambda: self._err(str(ex)))

    # UPDATE CARDS 
    def _update(self, cityname, aqi, pm25, pm10, no2, wt, wa, ft, fa):
        cat, cat_col   = get_category(aqi)
        mt, mti, mc    = get_mask(aqi)

        self.city_lbl.config(text=cityname)
        self.aqi_lbl.config(text=str(aqi), fg=cat_col)
        self.cat_lbl.config(text=cat,      fg=cat_col)
        self.pm25_val.config(text=f"{pm25:.1f}")
        self.pm10_val.config(text=f"{pm10:.1f}")
        self.no2_val.config(text=f"{no2:.1f}")
        self.mask_lbl.config(text=mt,  fg=mc)
        self.mask_tip.config(text=mti)
        self.status_var.set(f"✅ Live data loaded for {cityname}")

        self._draw(cityname, aqi, pm25, pm10, no2,
                   wt, wa, ft, fa, cat_col)
        self.btn.config(state="normal", text="Check AQI →")

    # DRAW CHARTS 
    def _draw(self, cityname, aqi, pm25, pm10, no2,
              wt, wa, ft, fa, cat_col):

        # Clear old charts
        for w in self.chart_inner.winfo_children():
            w.destroy()

        # Pandas DataFrames
        df_poll = pd.DataFrame({'Pollutant': ['PM2.5','PM10','NO2'],
                                'Value':     [pm25,   pm10,  no2]})
        df_week = pd.DataFrame({'Date': wt, 'AQI': wa})
        df_fc   = pd.DataFrame({'Time': ft, 'AQI': fa})

        # Figure — tall enough so 3 charts don't overlap
        fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(8.5, 11))
        fig.patch.set_facecolor(BG)
        fig.suptitle(f"Air Quality Dashboard — {cityname}",
                     fontsize=12, fontweight='bold',
                     color=TEXT, y=0.995)

        # Chart 1 — Bar: Current Pollutants
        ax1.set_facecolor(CARD)
        bars = ax1.bar(df_poll['Pollutant'], df_poll['Value'],
                       color=['#e04c4c','#f0934c','#4c8ef0'],
                       edgecolor=BORDER, linewidth=0.5, width=0.4)
        for bar, val in zip(bars, df_poll['Value']):
            ax1.text(bar.get_x() + bar.get_width()/2,
                     bar.get_height() + 0.3, f"{val:.1f}",
                     ha='center', va='bottom',
                     color=TEXT, fontsize=9, fontweight='bold')
        ax1.set_title(f"Current Pollutant Levels  |  AQI: {aqi}",
                      color=TEXT, fontsize=10, pad=8)
        ax1.set_ylabel("Concentration (µg/m³)", color=SUBTEXT, fontsize=9)
        ax1.tick_params(colors=TEXT, labelsize=9)
        ax1.spines[:].set_edgecolor(BORDER)

        # Chart 2 — Line: 7-Day Trend
        ax2.set_facecolor(CARD)
        if not df_week.empty:
            sns.lineplot(data=df_week, x='Date', y='AQI',
                         ax=ax2, color=GREEN,
                         linewidth=2, marker='o', markersize=7)
            ax2.fill_between(df_week['Date'], df_week['AQI'],
                             alpha=0.15, color=GREEN)
            ax2.axhline(y=100, color='#f0d34c', linestyle='--',
                        alpha=0.7, linewidth=1, label='Moderate (100)')
            ax2.axhline(y=150, color='#f0934c', linestyle='--',
                        alpha=0.7, linewidth=1, label='Sensitive (150)')
            ax2.xaxis.set_major_formatter(mdates.DateFormatter('%a\n%d %b'))
            ax2.legend(fontsize=8, facecolor=CARD,
                       labelcolor=TEXT, framealpha=0.7)
        ax2.set_title("7-Day AQI Historical Trend",
                      color=TEXT, fontsize=10, pad=8)
        ax2.set_ylabel("AQI", color=SUBTEXT, fontsize=9)
        ax2.set_xlabel("")
        ax2.tick_params(colors=TEXT, labelsize=9)
        ax2.spines[:].set_edgecolor(BORDER)

        # Chart 3 — Line: 24hr Forecast
        ax3.set_facecolor(CARD)
        sns.lineplot(data=df_fc, x='Time', y='AQI',
                     ax=ax3, color='#a78bfa',
                     linewidth=2, marker='o', markersize=4)
        ax3.fill_between(df_fc['Time'], df_fc['AQI'],
                         alpha=0.15, color='#a78bfa')
        ax3.plot(df_fc['Time'].iloc[0], df_fc['AQI'].iloc[0],
                 'o', color='white', markersize=9,
                 label=f'Now: AQI {aqi}', zorder=5)
        ax3.axhline(y=50,  color='#4cf0b4', linestyle='--',
                    alpha=0.5, linewidth=1, label='Good (50)')
        ax3.axhline(y=100, color='#f0d34c', linestyle='--',
                    alpha=0.5, linewidth=1, label='Moderate (100)')
        ax3.axhline(y=150, color='#f0934c', linestyle='--',
                    alpha=0.5, linewidth=1, label='Sensitive (150)')
        ax3.axhline(y=200, color='#e04c4c', linestyle='--',
                    alpha=0.5, linewidth=1, label='Unhealthy (200)')
        ax3.xaxis.set_major_formatter(mdates.DateFormatter('%I %p'))
        ax3.xaxis.set_major_locator(mdates.HourLocator(interval=3))
        plt.setp(ax3.xaxis.get_majorticklabels(),
                 rotation=30, ha='right', fontsize=8)
        ax3.legend(fontsize=8, facecolor=CARD,
                   labelcolor=TEXT, framealpha=0.7)
        ax3.set_title("24-Hour AQI Forecast",
                      color=TEXT, fontsize=10, pad=8)
        ax3.set_ylabel("AQI", color=SUBTEXT, fontsize=9)
        ax3.set_xlabel("Time", color=SUBTEXT, fontsize=9)
        ax3.tick_params(colors=TEXT, labelsize=9)
        ax3.spines[:].set_edgecolor(BORDER)

        # Generous spacing so charts never overlap
        plt.subplots_adjust(top=0.96, bottom=0.07,
                            left=0.10, right=0.97,
                            hspace=0.45)

        # Save PNG
        fig.savefig('air_quality_report.png', dpi=150,
                    bbox_inches='tight', facecolor=BG)

        # Embed in scrollable Tkinter canvas
        canvas = FigureCanvasTkAgg(fig, master=self.chart_inner)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)
        plt.close(fig)

        # Reset scroll to top
        self.chart_canvas.yview_moveto(0)

    # ERROR 
    def _err(self, msg):
        self.status_var.set(f"❌ {msg}")
        self.btn.config(state="normal", text="Check AQI →")
        messagebox.showerror("Error", msg)


if __name__ == "__main__":
    root = tk.Tk()
    AirWatchApp(root)
    root.mainloop()
 