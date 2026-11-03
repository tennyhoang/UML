"""Writes data/hms_reference.json, data/sensor_reference.json, prompts/*.txt and config.free.json.
EDIT THE TEXTS BELOW if you want different wording; run `python make_inputs.py` again.

IMPORTANT (honesty): the three prompt texts, the paraphrases and the two reference models below were written for
this project from the description in Table I of Iftikhar & Rausch (2026). They are NOT the original authors' files.
State this in the paper, and have an expert on your team review the reference models before you run anything."""
import json, os

def A(n, t="string", v="-"): return {"name": n, "type": t, "visibility": v}
def O(n, v="+"): return {"name": n, "visibility": v}
def C(name, attrs=(), ops=(), abstract=False, interface=False):
    d = {"name": name, "attributes": [A(*a) if isinstance(a, tuple) else A(a) for a in attrs], "operations": [O(o) for o in ops]}
    if abstract: d["abstract"] = True
    if interface: d["interface"] = True
    return d
def R(t, s, d, ms=None, md=None, label=None):
    r = {"type": t, "source": s, "target": d}
    if ms: r["multiplicity_source"] = ms
    if md: r["multiplicity_target"] = md
    if label: r["label"] = label
    return r

HMS = {"classes": [
    C("Patient", ["id", "name", "address"], ["getBillableDays"], abstract=True),
    C("InPatient", ["ward", "admissionDate"], ["getDailyRate"]),
    C("OutPatient", ["clinic", "visitDate"], ["getVisitFee"]),
    C("Bill", ["billId", ("amount", "double"), "date"], ["getAmount"]),
    C("BillingStrategy", [], ["calculate"], interface=True),
    C("InsuranceBilling", ["insurerName"], ["calculate"]),
    C("SelfPayBilling", [], ["calculate"]),
    C("GovernmentBilling", ["schemeCode"], ["calculate"]),
    C("BillingProcessor", [], ["processBill", "setStrategy"])],
 "relationships": [
    R("inheritance", "InPatient", "Patient"), R("inheritance", "OutPatient", "Patient"),
    R("realization", "InsuranceBilling", "BillingStrategy"), R("realization", "SelfPayBilling", "BillingStrategy"),
    R("realization", "GovernmentBilling", "BillingStrategy"),
    R("aggregation", "BillingProcessor", "BillingStrategy", "1", "1"),
    R("association", "BillingProcessor", "Patient", "1", "*", "bills"),
    R("association", "BillingProcessor", "Bill", "1", "*", "produces"),
    R("association", "Patient", "Bill", "1", "*", "receives")]}

SENSOR = {"classes": [
    C("Sensor", ["sensorId", "location", ("reading", "double")], ["measure", "getReading"], abstract=True),
    C("PressureSensor", [], ["measure"]), C("TemperatureSensor", [], ["measure"]),
    C("RainGauge", [], ["measure"]), C("WindSensor", ["direction"], ["measure"]),
    C("Subject", [], ["attach", "detach", "notifyObservers"], interface=True),
    C("Observer", [], ["update"], interface=True),
    C("WeatherStation", ["stationId"], ["attach", "detach", "notifyObservers", "collect"]),
    C("WeatherInformationSystem", ["name"], ["update", "store"]),
    C("ReportingStrategy", [], ["shouldReport"], interface=True),
    C("HourlyReporting", [], ["shouldReport"]),
    C("CustomIntervalReporting", [("intervalMinutes", "int")], ["shouldReport"]),
    C("ReportingContext", [], ["setStrategy", "report"])],
 "relationships": [
    R("inheritance", "PressureSensor", "Sensor"), R("inheritance", "TemperatureSensor", "Sensor"),
    R("inheritance", "RainGauge", "Sensor"), R("inheritance", "WindSensor", "Sensor"),
    R("realization", "WeatherStation", "Subject"), R("realization", "WeatherInformationSystem", "Observer"),
    R("aggregation", "WeatherStation", "Sensor", "1", "*"),
    R("association", "Subject", "Observer", "1", "*", "notifies"),
    R("realization", "HourlyReporting", "ReportingStrategy"), R("realization", "CustomIntervalReporting", "ReportingStrategy"),
    R("aggregation", "ReportingContext", "ReportingStrategy", "1", "1"),
    R("association", "WeatherStation", "ReportingContext", "1", "1")]}

HMS_P = {
 "P1": "A hospital management system must bill patients. Some patients are admitted to a ward and some visit as outpatients. Charges depend on how the bill is paid: private insurance, out-of-pocket payment by the patient, or a government health scheme, and each of them calculates the amount differently. The hospital may add further payment arrangements later. Design the class diagram for the billing part of this system.",
 "P2": "Design a UML class diagram for hospital billing. The hospital treats admitted patients (who stay in a ward) and outpatients (who attend a clinic for a visit). A bill is paid through insurance, directly by the patient, or by a government programme; the amount is computed in a different way for each. New ways of paying may be introduced in the future.",
 "P3": "Model the billing of a hospital as a class diagram. Patients are either inpatients or outpatients. The cost of a bill is worked out differently depending on whether the patient is covered by an insurer, pays personally or is covered by a government scheme, and the hospital expects that other payment methods will be added over time."}
SEN_P = {
 "P1": "A weather monitoring network uses several kinds of sensors: pressure sensors, temperature sensors, rain gauges and wind sensors. A weather station collects their readings. Whenever new readings are available, the weather information system that depends on the station must be informed. Readings are reported either every hour or at a custom interval chosen by the operator, and other reporting schedules may be needed later. Design the class diagram for this system.",
 "P2": "Design a UML class diagram for a sensor network that monitors weather. Pressure, temperature, rainfall and wind are measured by different sensor types. A weather station gathers the measurements and the weather information system must be kept up to date when the measurements change. Reports are issued hourly or at an interval set by the operator, and additional reporting rules may be added in the future.",
 "P3": "Model an event-driven weather sensor network as a class diagram. The network has pressure sensors, temperature sensors, rain gauges and wind sensors. A weather station receives their data and has to tell the weather information system whenever the data change. The frequency of reporting can be hourly or user-defined, and the operator may want new reporting policies later."}

STANDARD = "You are a software designer. Produce a UML class diagram for the following task."
RULE = ("You are an experienced object-oriented software architect.\n"
        "Design principles you must apply: (1) Abstraction: when several classes share attributes or behaviour, extract a common "
        "abstract superclass or interface. (2) Encapsulation: attributes are private; expose behaviour through operations. "
        "(3) Open/closed and separation of concerns: when a behaviour varies, put each variant in its own class behind a common "
        "interface instead of using conditionals, and let a client class refer to that interface. (4) When one object must keep "
        "other objects informed about its changes, decouple them through interfaces instead of direct calls.\n"
        "Before answering, check that every class is connected, every association has multiplicities, there are no duplicate or "
        "cyclic inheritance links, and every interface is used by some class. Then give the final diagram.")

# Five good/bad pairs from domains that are NOT HMS or the sensor network (the base study keeps the benchmarks out of the examples).
PAIRS = [
 ("An online shop sells physical and downloadable products and supports card, wallet and bank-transfer payment.",
  "Product(name, price, type, fileSize, weight) with public attributes; Order has a method pay(method) using if/else for card, wallet, bank-transfer.",
  "abstract Product with PhysicalProduct and DigitalProduct; private attributes; interface PaymentMethod realized by CardPayment, WalletPayment, BankTransferPayment; Checkout aggregates PaymentMethod (1..1)."),
 ("A library lends books, DVDs and magazines to members, and late fees depend on the item type.",
  "Separate unrelated classes Book, DVD, Magazine, each repeating title, id and dueDate; Member has a method with if/else on the item type to compute the fee.",
  "abstract LibraryItem(title, id, dueDate) specialised by Book, DVD, Magazine; interface FeePolicy with concrete policies; Loan aggregates FeePolicy; Member 1..* Loan."),
 ("A ride-hailing app has cars, bikes and scooters, and the fare is computed by distance, by time or by a flat rate.",
  "Vehicle(type, plate) with a type string; Trip.fare() contains a switch on the pricing kind; attributes public.",
  "abstract Vehicle specialised by Car, Bike, Scooter; interface FarePolicy with DistanceFare, TimeFare, FlatFare; Trip refers to FarePolicy; Trip 0..* to Vehicle 1."),
 ("A newsroom publishes breaking news; web, email and mobile channels must all be told when a story is published.",
  "Newsroom holds fields webSite, emailList, mobileApp and calls each directly in publish(); any new channel needs a change in Newsroom.",
  "interface Subscriber(notify) realized by WebChannel, EmailChannel, MobileChannel; Newsroom keeps Subscriber 0..* and notifies them; Story belongs to Newsroom."),
 ("A restaurant serves dine-in, takeaway and delivery orders, and discounts are student, loyalty or seasonal.",
  "Order class with a type field and a discount() method of nested if statements; no relation between order kinds.",
  "abstract Order specialised by DineInOrder, TakeawayOrder, DeliveryOrder; interface DiscountRule realized by StudentDiscount, LoyaltyDiscount, SeasonalDiscount; Order uses DiscountRule (0..1)."),
]
PREF = (RULE + "\n\nBelow are five annotated examples. In each one a WORSE design and a PREFERRED design are shown for a task; "
        "always aim for the structure of the preferred design.\n" +
        "".join(f"\nExample {i}\nTask: {t}\nWORSE: {w}\nPREFERRED: {g}\n" for i, (t, w, g) in enumerate(PAIRS, 1)))

cfg = {
 "temperature": 0.5, "k_max": 3, "runs": 10,
 "conditions": ["C0", "C1", "C2", "C3", "C4", "C5"],
 "json_instruction": json.load(open("config.example.json"))["json_instruction"],
 "prompts": {"standard": {"system": STANDARD}, "rule": {"system": RULE}, "preference": {"system": PREF}},
 "models": {
   "gemini-3.6-flash":  {"provider": "gemini", "name": "gemini-3.6-flash", "min_interval": 7},
   "gpt-oss-120b":      {"provider": "openai_compat", "name": "openai/gpt-oss-120b", "base_url": "https://api.groq.com/openai/v1",
                         "api_key_env": "GROQ_API_KEY", "min_interval": 4},
   "llama-3.1-8b":      {"provider": "openai_compat", "name": "llama-3.1-8b-instant", "base_url": "https://api.groq.com/openai/v1",
                         "api_key_env": "GROQ_API_KEY", "min_interval": 4}},
 "domains": {
   "HMS":    {"packs": [], "dry_seed": "data/hms_flawed_example.json", "prompts": HMS_P, "reference": "data/hms_reference.json"},
   "Sensor": {"packs": ["notification"], "dry_seed": "data/hms_flawed_example.json", "prompts": SEN_P, "reference": "data/sensor_reference.json"}}}

if __name__ == "__main__":
    os.makedirs("data", exist_ok=True); os.makedirs("prompts", exist_ok=True)
    json.dump(HMS, open("data/hms_reference.json", "w"), indent=1)
    json.dump(SENSOR, open("data/sensor_reference.json", "w"), indent=1)
    for k, v in cfg["prompts"].items(): open(f"prompts/{k}.txt", "w").write(v["system"])
    for d, P in (("hms", HMS_P), ("sensor", SEN_P)):
        for k, v in P.items(): open(f"prompts/{d}_{k}.txt", "w").write(v)
    json.dump(cfg, open("config.free.json", "w"), indent=1, ensure_ascii=False)
    print("written: config.free.json, data/*_reference.json, prompts/*.txt")
