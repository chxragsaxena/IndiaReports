"""Hand-labelled pairs for the duplicate check: a new report and an existing open report of the same
category, how far apart they are, and whether a person would say they are the SAME real-world problem.

Written by one person, so they reflect one person's idea of "same problem". They include the hard
cases on purpose: two different problems close together, and one problem described in two languages.
"""

# (id, new title, new description, existing title, existing description, metres apart, same problem?, what it tests)
CASES = [
    # ---- the same problem, worded alike or paraphrased (English) ----
    ("p01", "Large pothole near bus stop", "Deep pothole on the road near the bus stop, dangerous for bikes", "Pothole near bus stop", "Big hole in road by the bus stop", 12, True, "same words"),
    ("p02", "Garbage not collected near market", "Garbage has not been collected for a week near the vegetable market", "Rubbish heaps outside the market", "Rubbish not cleared outside the vegetable market for days", 40, True, "paraphrase"),
    ("p03", "Street light not working on 5th cross", "The street light is off and the lane is dark at night", "Streetlight broken at 5th cross", "Whole lane is dark since the street light stopped working", 25, True, "paraphrase"),
    ("p04", "Water pipe burst flooding the road", "Water is flooding the road from a burst pipe", "Pipeline leaking", "Water from the pipeline is all over the street", 60, True, "paraphrase"),
    ("p05", "Open drain overflowing near school", "The open drain is overflowing near the school gate", "Drain overflowing with sewage", "Sewage from the drain overflowing near the school", 35, True, "same words"),
    ("p06", "Open manhole without cover on footpath", "Manhole has no cover on the footpath, someone may fall in", "Manhole cover missing near footpath", "The manhole cover is missing on the footpath", 18, True, "same words"),
    ("p07", "No water supply since two days", "Tap water has not come for two days in our colony", "Tap water not coming", "No water in the taps for two days in this colony", 100, True, "paraphrase"),
    ("p08", "Burning garbage near park causing smoke", "Someone is burning garbage next to the park and smoke is everywhere", "Trash being burnt beside the park", "Heavy smoke from burning trash beside the park", 55, True, "paraphrase"),
    ("p09", "Road broken after rain near temple", "The road near the temple is broken after the rains", "Road damaged near the temple", "Road near the temple damaged by the rains", 33, True, "same words"),
    ("p10", "Signal not working at crossing", "The traffic signal at the crossing is not working and there is chaos", "Traffic light off at the junction", "Traffic light is off at the junction and cars are stuck", 45, True, "paraphrase"),
    ("p11", "Power cut every evening in our lane", "There is a power cut every evening in our lane for three hours", "Daily power outage in this street", "Power outage every evening from six to nine in this street", 70, True, "paraphrase"),
    ("p12", "Pothole", "Pothole", "Pothole", "Pothole", 5, True, "identical"),
    ("p13", "Garbage dump overflowing", "The garbage dump at the corner is overflowing onto the road", "Overflowing garbage bin at the corner", "The garbage bin at the corner is overflowing onto the road", 20, True, "same words"),
    ("p14", "Street light flickering outside hospital", "Street light keeps flickering outside the hospital entrance", "Light flickering at hospital entrance", "The street light at the hospital entrance keeps flickering", 28, True, "same words"),
    # ---- the same problem in Hindi / Hinglish ----
    ("h01", "सड़क पर बड़ा गड्ढा है", "सड़क पर बहुत बड़ा गड्ढा है जिससे गाड़ियाँ फँस रही हैं", "सड़क में गड्ढा", "सड़क के बीच में गड्ढा, बाइक वालों को खतरा", 20, True, "Hindi paraphrase"),
    ("h02", "कूड़ा नहीं उठाया गया", "तीन दिन से कूड़ा नहीं उठाया गया है", "कूड़ा तीन दिन से पड़ा है", "गली में कूड़ा तीन दिन से पड़ा है कोई नहीं उठाता", 50, True, "Hindi paraphrase"),
    ("h03", "स्ट्रीट लाइट खराब है", "हमारी गली की स्ट्रीट लाइट खराब है", "स्ट्रीट लाइट बंद पड़ी है", "गली की स्ट्रीट लाइट कई दिनों से बंद पड़ी है", 15, True, "Hindi paraphrase"),
    ("h04", "kachra nahi uthaya gaya", "kachra 3 din se pada hai koi nahi uthata", "kooda 3 din se pada hai", "kooda nahi uthaya gaya 3 din se", 50, True, "Hinglish spelling differences"),
    # ---- the same problem in two languages (words cannot match) ----
    ("x01", "Pothole on main road", "Big pothole on the main road", "मुख्य सड़क पर गड्ढा", "मुख्य सड़क पर बड़ा गड्ढा है", 10, True, "English vs Hindi, same spot"),
    ("x02", "Pothole on main road", "Big pothole on the main road", "मुख्य सड़क पर गड्ढा", "मुख्य सड़क पर बड़ा गड्ढा है", 90, True, "English vs Hindi, 90 m apart"),
    ("x03", "Street light broken", "The street light in our lane is broken", "स्ट्रीट लाइट टूटी है", "हमारी गली की स्ट्रीट लाइट टूटी हुई है", 80, True, "English vs Hindi, 80 m apart"),
    ("x04", "Drain overflowing", "Drain is overflowing onto the road", "சாக்கடை நிரம்பி வழிகிறது", "கழிவுநீர் சாலையில் ஓடுகிறது", 25, True, "English vs Tamil, same spot"),
    # ---- different problems, easy: nothing in common, not at the same spot ----
    ("n01", "Pipe leaking on road", "A water pipe is leaking on the road", "No water in taps", "No water in the taps since morning", 80, False, "different, no overlap"),
    ("n02", "Garbage near market", "Garbage lying near the vegetable market", "Illegal parking blocks lane", "Cars are parked illegally and block the lane", 60, False, "different, no overlap"),
    ("n03", "Street light off", "The street light on the corner is off", "Water logging after rain", "Heavy water logging after the rain", 100, False, "different, no overlap"),
    ("n04", "सड़क पर गड्ढा", "सड़क पर बड़ा गड्ढा", "नाली जाम है", "गली की नाली जाम है", 70, False, "different, Hindi"),
    ("n05", "Power cut in lane", "Power cut every evening", "Transformer making loud noise", "The transformer makes a loud noise at night", 90, False, "different, no overlap"),
    # ---- identical wording but too far apart ----
    ("n06", "Large pothole near bus stop", "Deep pothole near the bus stop", "Large pothole near bus stop", "Deep pothole near the bus stop", 200, False, "same words, 200 m away"),
    ("n07", "Garbage not collected", "Garbage not collected for a week", "Garbage not collected", "Garbage not collected for a week", 400, False, "same words, 400 m away"),
    ("n08", "Street light not working", "Street light not working on our road", "Street light not working", "Street light not working on our road", 151, False, "same words, just outside 150 m"),
    # ---- the hard negatives: a different problem of the same kind, close by ----
    ("t01", "Pothole near bus stop", "Pothole on the road near the bus stop", "Pothole outside hospital gate", "Pothole outside the hospital gate", 120, False, "another pothole 120 m away"),
    ("t02", "Garbage not collected near market", "Garbage not collected near the market", "Garbage bin overflowing at bus stop", "The garbage bin is overflowing at the bus stop", 110, False, "another garbage spot"),
    ("t03", "Street light off in lane 3", "The street light in lane 3 is off", "Street light off in lane 4", "The street light in lane 4 is off", 90, False, "neighbouring lane"),
    ("t04", "Pothole near school", "Pothole on the road near the school", "Speed breaker needed outside school", "A speed breaker is needed outside the school", 60, False, "related but different"),
    ("t05", "Drain choked near temple", "The drain near the temple is choked", "Drain cover broken near temple", "The drain cover near the temple is broken", 40, False, "different drain problem"),
    ("t06", "Pothole", "Pothole", "Speed breaker broken", "The speed breaker is broken", 10, False, "different problem at the same spot"),
    ("t07", "Garbage near park", "Garbage thrown near the park", "Dead animal near park", "A dead animal is lying near the park", 25, False, "different problem at the same spot"),
    ("t08", "Water pipe leaking near station", "A water pipe is leaking near the railway station", "Water supply dirty near station", "The supply water near the railway station is dirty", 70, False, "related water problems"),
    ("t09", "Street light off near bridge", "The street light near the bridge is off", "Street light too dim near bridge", "The street light near the bridge is too dim", 80, False, "related light problems"),
    ("t10", "Road broken near market", "The road near the market is broken", "Road blocked by vendors near market", "Vendors block the road near the market", 50, False, "same words, different problem"),
    ("t11", "सड़क पर गड्ढा", "सड़क पर बड़ा गड्ढा है", "सड़क पर पानी भरा है", "सड़क पर बारिश का पानी भरा है", 80, False, "Hindi, different problem, shared word"),
    ("t12", "Traffic jam at crossing every morning", "Traffic jam at the crossing every morning", "Signal not working at crossing", "The signal at the crossing is not working", 60, False, "related traffic problems"),
]
