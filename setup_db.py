import sqlite3
from werkzeug.security import generate_password_hash

# Connect to database
connection = sqlite3.connect('physio.db')
cursor = connection.cursor()

# ==============================================================================
# 1. Create Users Table
# ==============================================================================
cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
""")

# ==============================================================================
# 2. Create Protocols Table (16 Columns)
# ==============================================================================
cursor.execute("""
    CREATE TABLE IF NOT EXISTS protocols (
        id INTEGER PRIMARY KEY,
        disease_name TEXT,
        keywords TEXT,
        description TEXT,
        estim_type TEXT,
        estim_params TEXT,
        estim_placement TEXT,
        estim_image TEXT,
        estim_role TEXT,
        us_indication TEXT,
        us_params TEXT,
        us_role TEXT,
        exercises_list TEXT,
        treatment_duration TEXT,
        expected_recovery TEXT,
        reference TEXT
    )
""")

# ==============================================================================
# 3. Insert Data (16 Values per Disease)
# ==============================================================================

# 1. Frozen Shoulder
cursor.execute("""
    INSERT INTO protocols VALUES (
        NULL,
        'Adhesive Capsulitis (Frozen Shoulder)',
        'stiffness, shoulder pain, capsulitis, الكتف المتجمد',
        'A painful disorder where the shoulder capsule becomes inflamed and stiff.',
        'TENS (High Rate)',
        'Freq: 100-150 Hz. Width: 50-80 µs. Time: 20 mins.',
        'Bracket Method: 2 electrodes anterior/posterior to the joint.',
        '/static/shoulder.jpg', 
        'Pain modulation via Gate Control Theory.',
        'Indicated (Continuous)', '1 MHz (deep), 1.5 W/cm², 100%.', 'Deep heating for extensibility.',
        '1. Pendulum Exercises.\n2. Wall Climb.\n3. Wand Exercises.',
        'Session: 45-60 mins.', 'Recovery: 3-12 months.', 'JOSPT Guidelines'
    )
""")

# 2. Lumbar Disc Herniation
cursor.execute("""
    INSERT INTO protocols VALUES (
        NULL,
        'Lumbar Disc Herniation (Sciatica)',
        'back pain, sciatica, disc, ديسك, عرق النسا',
        'Disc material displacement compressing the nerve root.',
        'IFC (Interferential)',
        'Carrier: 4000Hz. Beat: 80-150Hz. Vector: On.',
        'Paravertebral: Two channels crossing at the level of pain (L4-S1).',
        '/static/back.jpg',
        'Deep pain relief and muscle relaxation.',
        'Not for Disc', 'Avoid direct spinal application.', 'Muscle spasm relief only.',
        '1. McKenzie Extension.\n2. Nerve Flossing.\n3. Core Stability.',
        'Session: 45 mins.', 'Recovery: 3-6 months.', 'NASS Guidelines'
    )
""")

# 3. Knee Osteoarthritis
cursor.execute("""
    INSERT INTO protocols VALUES (
        NULL,
        'Knee Osteoarthritis',
        'knee pain, oa, stiffness, خشونة الركبة',
        'Degenerative wear-and-tear arthritis of the knee.',
        'NMES (Strengthening)',
        'Target: Quads. Freq: 50Hz. Duty: 10/50. Intensity: Motor.',
        'One electrode on VMO motor point, one on proximal Femoral Nerve trunk.',
        '/static/knee.jpg',
        'Strengthening Quadriceps to offload joint.',
        'Indicated', 'Pulsed 20% or Continuous. 1 MHz.', 'Pain relief.',
        '1. Quad Sets.\n2. SLR.\n3. Mini Squats.',
        'Lifelong management.', 'Pain reduction in 4-8 weeks.', 'OARSI Guidelines'
    )
""")

# 4. Total Knee Arthroplasty (TKA)
cursor.execute("""
    INSERT INTO protocols VALUES (
        NULL,
        'Total Knee Arthroplasty (Post-Op TKA)',
        'knee replacement, tka, surgery, joint replacement, تغيير مفصل الركبة',
        'Rehabilitation following surgical replacement of the knee joint due to severe OA.',
        'NMES (Neuromuscular Electrical Stimulation)',
        'Target: Quadriceps. Freq: 50Hz. Intensity: Max tollerated. Time: 15-20 mins.',
        'One electrode on VMO motor point, one on proximal Femoral Nerve trunk.',
        '/static/tka.jpg',
        'Crucial for reversing quadriceps inhibition (AMI) immediately post-op.',
        'Generally Not Indicated',
        'Avoid heat/US over metal implants directly. Cryotherapy is preferred.',
        'Use Cryotherapy (Ice) for swelling control.',
        'Phase 1 (0-2 wks): Ankle pumps, Quad sets, Heel slides (ROM 0-90).\nPhase 2 (3-6 wks): Mini squats, Gait training, Stationary bike.\nPhase 3: Functional training.',
        '3-4 months supervised PT.',
        'Return to normal low-impact activities in 3-6 months.',
        'Ranawat et al. Consensus Guidelines'
    )
""")

# 5. Total Hip Arthroplasty (THA)
cursor.execute("""
    INSERT INTO protocols VALUES (
        NULL,
        'Total Hip Arthroplasty (Post-Op THA)',
        'hip replacement, tha, hip surgery, تغيير مفصل الفخذ',
        'Rehabilitation after hip joint replacement. *Precautions depend on surgical approach.*',
        'TENS (for incisional pain)',
        'Freq: 100Hz. Intensity: Sensory. Continuous.',
        'Electrodes placed parallel to the incision line (at least 2cm away). Do not place directly over staples.',
        '/static/tha.jpg',
        'Pain management to facilitate early mobilization.',
        'Contraindicated over Plastic/Metal',
        'Do not use Ultrasound over the prosthesis (risk of heating/loosening).',
        'N/A',
        '1. Ankle Pumps.\n2. Glute Squeeze.\n3. Heel Slides (within limit).\n4. Abduction (Avoid crossing midline).\n*Adhere to dislocation precautions.*',
        '2-3 months.',
        'Full weight bearing usually immediate (cemented) or 6 weeks (uncemented).',
        'HSS Rehabilitation Guidelines'
    )
""")

# 6. Rotator Cuff Repair (Post-Op)
cursor.execute("""
    INSERT INTO protocols VALUES (
        NULL,
        'Rotator Cuff Repair (Post-Op)',
        'shoulder surgery, supraspinatus tear, cuff repair, قطع وتر الكتف',
        'Rehab following surgical reattachment of torn rotator cuff tendons.',
        'TENS (Post-op Pain)',
        'Freq: 100Hz. Mode: Continuous. Time: As needed.',
        'Two channels crossing the shoulder joint (Anterior/Posterior and Lateral).',
        '/static/rotator.jpg',
        'Pain control during passive motion phase.',
        'Not indicated in early phase',
        'Can weaken suture repair in first 6 weeks. Avoid.',
        'N/A',
        'Phase 1 (0-6 wks): PROM only (Pendulums, Pulleys). NO Active motion.\nPhase 2 (6-12 wks): AAROM -> AROM.\nPhase 3 (12+ wks): Strengthening.',
        '4-6 months.',
        'Full return to sport/heavy labor: 6-9 months.',
        'ASES Rehabilitation Protocol'
    )
""")

# 7. Mechanical Neck Pain
cursor.execute("""
    INSERT INTO protocols VALUES (
        NULL,
        'Mechanical Neck Pain',
        'neck pain, cervical, stiffness, trapezius spasm, شد عضلات الرقبة',
        'Generalized neck pain provoked by sustained postures or movement.',
        'TENS (Burst Mode)',
        'Freq: 2-4 Hz (Burst). Pulse: 200 µs. Intensity: Visible twitch. Time: 20 mins.',
        'Paravertebral (Cervical paraspinals) and Upper Trapezius.',
        '/static/neck.jpg',
        'Endorphin release for chronic neck pain and muscle relaxation.',
        'Indicated (Thermal)',
        'Frequency: 1 MHz (Trapezius) or 3 MHz (Cervical). Continuous. 1.0 W/cm².',
        'Increase blood flow and relax tight suboccipital/paraspinal muscles.',
        '1. Chin Tucks (Deep Neck Flexor activation).\n2. Upper Trapezius Stretch.\n3. Levator Scapulae Stretch.\n4. Scapular Retraction exercises.',
        'Session: 45 mins. Freq: 2-3/week.',
        'Improvement usually seen within 2-4 weeks.',
        'APTA Orthopaedic Section Guidelines'
    )
""")

# 8. ACL Reconstruction
cursor.execute("""
    INSERT INTO protocols VALUES (
        NULL,
        'ACL Reconstruction Rehab',
        'acl, knee ligament, surgery, sports injury, الرباط الصليبي',
        'Post-operative management of Anterior Cruciate Ligament reconstruction.',
        'NMES (Russian Current)',
        'Target: Quads (VMO). 2500Hz burst. 10/50 duty cycle. Intensity: Motor.',
        'Bipolar placement: VMO motor point and Proximal Rectus Femoris.',
        '/static/acl.jpg',
        'Restore quad strength and prevent atrophy (Essential in first 6 weeks).',
        'Not primary modality',
        'Cryotherapy is superior for post-op swelling.',
        'N/A',
        'Wk 1-2: Full extension emphasis, Patellar mobs, SLR.\nWk 3-6: Closed chain (Squats, Lunges), Proprioception.\nMonth 3+: Running drills.',
        '6-9 months.',
        'Return to sport: 9-12 months (Must pass Hop Tests).',
        'Moon et al. / Delaware Protocol'
    )
""")

# 9. Hamstring Strain
cursor.execute("""
    INSERT INTO protocols VALUES (
        NULL,
        'Hamstring Muscle Strain',
        'pulled muscle, thigh pain, sprinter injury, posterior thigh, مزق العضلة الخلفية',
        'Tear of muscle fibers in the posterior thigh.',
        'Pulsed Shortwave or IFC',
        'IFC: 4000Hz, Vector scan for pain.',
        'Quadripolar (4 electrodes) surrounding the site of pain/strain on posterior thigh.',
        '/static/hamstring.jpg',
        'Pain relief and hematoma absorption (sub-acute).',
        'Indicated (Pulsed initially)',
        'Acute: Pulsed 20%, 1MHz. Chronic: Continuous 1MHz, 1.5 W/cm².',
        'Promote collagen alignment during healing.',
        'Phase 1: Isometric Hamstring sets, Ice.\nPhase 2: Eccentric loading (Nordic Hamstring Curl).\nPhase 3: Sprinting mechanics.',
        '4-8 weeks.',
        'High recurrence rate if eccentric strengthening is neglected.',
        'Aspetar Hamstring Protocol'
    )
""")

# 10. Meniscus Tear
cursor.execute("""
    INSERT INTO protocols VALUES (
        NULL,
        'Meniscus Tear (Conservative/Post-Op)',
        'knee locking, clicking, cartilage tear, ghoda, غضروف الركبة',
        'Injury to the shock-absorbing cartilage in the knee.',
        'NMES / TENS',
        'NMES for Quad strength. TENS for joint line pain.',
        'NMES: On Quads. TENS: Medial and Lateral joint line.',
        '/static/meniscus.jpg',
        'Muscle support to offload the compartment.',
        'Indicated (Pulsed)',
        'Low intensity pulsed ultrasound (LIPUS) may aid healing in vascular zones.',
        'Symptom management.',
        '1. Range of Motion (Bike).\n2. Open chain quads (avoid deep flexion initially).\n3. Balance/Proprioception.',
        'Conservative: 6-8 weeks. Repair: 4-6 months.',
        'Surgery indicated if locking/catching persists.',
        'JOSPT Guidelines'
    )
""")

# 11. Ankle Sprain
cursor.execute("""
    INSERT INTO protocols VALUES (
        NULL,
        'Lateral Ankle Sprain',
        'ankle pain, sprain, swelling, ligament tear, twist, التواء الكاحل',
        'Injury to the lateral ligaments (ATFL, CFL) usually caused by inversion trauma.',
        'HVPC / IFC',
        'Freq: 120 Hz. Polarity: Negative (for edema). Time: 20-30 mins.',
        'Surrounding the malleolus (Medial and Lateral) ensuring the current passes through the edema.',
        '/static/ankle.jpg',
        'Edema reduction (curbing swelling) in the acute phase.',
        'Indicated (Pulsed only in Acute)',
        'Acute: 20% Duty Cycle, 3 MHz, 0.5 W/cm². Chronic: 100%, 1 MHz.',
        'Acute: Accelerate healing. Chronic: Break down adhesions/scar tissue.',
        '1. RICE Protocol (Acute).\n2. Ankle Pumps (Range of Motion).\n3. Towel Scrunches (Intrinsics).\n4. Single Leg Balance (Proprioception).',
        'Mild: 2 weeks. Severe: 6-12 weeks.',
        'Return to sport depends on passing functional hop tests.',
        'NATA Position Statement on Ankle Sprains'
    )
""")

# 12. Tennis Elbow
cursor.execute("""
    INSERT INTO protocols VALUES (
        NULL,
        'Lateral Epicondylitis (Tennis Elbow)',
        'elbow pain, tennis elbow, grip weakness, forearm pain, التهاب الكوع',
        'Overuse injury involving the extensor carpi radialis brevis (ECRB) tendon.',
        'TENS (Conventional)',
        'Freq: 100 Hz. Pulse: 100 µs. Time: 15 mins.',
        'One electrode over the pain site (Lateral Epicondyle), one proximal over the muscle belly.',
        '/static/elbow.jpg',
        'Pain management to facilitate exercise performance.',
        'Indicated (Pulsed Mode)',
        'Frequency: 3 MHz. Intensity: 0.5-1.0 W/cm². Duty Cycle: 20% (Non-thermal). Time: 5 mins.',
        'Stimulate collagen synthesis and tendon healing.',
        '1. Eccentric Wrist Extension (Tyler Twist).\n2. Wrist Extensor Stretch.\n3. Grip Strengthening.',
        'Session: 30-45 mins. Freq: 2/week.',
        'Recovery typically takes 12 weeks to 6 months.',
        'Bisset et al. (Physiotherapy Evidence Database)'
    )
""")

# 13. Stroke
cursor.execute("""
    INSERT INTO protocols VALUES (
        NULL,
        'Stroke Rehabilitation (Hemiplegia)',
        'cva, stroke, paralysis, weakness, gait, hemiparesis, الجلطة الدماغية',
        'Rehabilitation for loss of motor function/sensation after cerebral infarction.',
        'FES (Functional Electrical Stimulation)',
        'Target: Tibialis Anterior (for Foot Drop).',
        'Active electrode on Tibialis Anterior motor point (below knee, lateral), Reference on tendon.',
        '/static/stroke.jpg',
        'Neuroplasticity and functional motor re-learning (Gait).',
        'Not typically indicated',
        'Focus is on neuro-facilitation techniques.',
        'N/A',
        '1. Task-Oriented Training (Reach to grasp).\n2. Sit-to-Stand practice.\n3. Gait Training.\n4. Constraint-Induced Movement Therapy (CIMT).',
        'Long term (Months to Years).',
        'Fastest recovery in first 3-6 months.',
        'AHA/ASA Stroke Rehab Guidelines'
    )
""")

# 14. Parkinson's
cursor.execute("""
    INSERT INTO protocols VALUES (
        NULL,
        'Parkinson''s Disease',
        'tremor, rigidity, shuffling gait, balance, pd, الشلل الرعاش',
        'Progressive neurodegenerative disorder affecting movement control.',
        'Biofeedback / Cueing',
        'Auditory (Metronome) or Visual cues.',
        'N/A (Cues are auditory/visual, not electrode based).',
        '/static/parkinson.jpg',
        'Overcome freezing of gait (FOG).',
        'N/A',
        'Not indicated.',
        'N/A',
        '1. LSVT BIG (Large amplitude movements).\n2. Rotational trunk exercises.\n3. Balance & Fall Prevention.\n4. Treadmill training.',
        'Lifelong maintenance.',
        'Goal is to delay decline and maintain independence.',
        'European Physiotherapy Guideline'
    )
""")

# 15. Bell's Palsy
cursor.execute("""
    INSERT INTO protocols VALUES (
        NULL,
        'Bell''s Palsy (Facial Palsy)',
        'facial paralysis, face droop, bell, weakness, شلل الوجه',
        'Unilateral weakness or paralysis of facial muscles due to inflammation of the 7th cranial nerve.',
        'Electrical Muscle Stimulation (EMS)',
        'Target: Individual facial muscles. Pulse: Long duration (for denervated) or standard EMS.',
        'Motor Point Stimulation: Specific placement on the belly of affected muscles.',
        '/static/face.jpg',
        'Maintain muscle bulk/prevent atrophy. *Biofeedback is preferred.*',
        'Not standard practice',
        'Not typically used for facial muscles due to proximity to eyes.',
        'N/A',
        '1. AAROM (Assisted Active ROM) for eyebrows, eyes, lips.\n2. Mime Therapy.\n3. Kabat Rehabilitation.\n4. Blowing/Whistling exercises.',
        'Session: 30 mins. Daily home exercises.',
        'Most recover within 3-6 months.',
        'Clinical Practice Guidelines (Otolaryngology)'
    )
""")

# 16. Diabetic Polyneuropathy
cursor.execute("""
    INSERT INTO protocols VALUES (
        NULL,
        'Diabetic Peripheral Neuropathy',
        'diabetes, numbness, foot pain, balance, burning feet, التهاب الأعصاب السكري',
        'Nerve damage caused by diabetes leading to loss of sensation.',
        'TENS / Infrared',
        'TENS: 80-100Hz. Infrared Anodyne Therapy.',
        'Electrodes placed along the dermatome of the leg/foot (e.g., L4, L5, S1) or surrounding painful area.',
        '/static/neuropathy.jpg',
        'Symptomatic pain relief and local circulation improvement.',
        'Caution',
        'Use with extreme caution due to loss of sensation (Burn risk).',
        'Avoid if sensation is absent.',
        '1. Balance Training.\n2. Gait Training.\n3. Foot Care Education.\n4. Aerobic exercise.',
        'Chronic management.',
        'Strict glycemic control is key.',
        'American Diabetes Association'
    )
""")

# 17. CABG (Open Heart)
cursor.execute("""
    INSERT INTO protocols VALUES (
        NULL,
        'CABG Rehabilitation (Open Heart)',
        'heart surgery, cardiac rehab, sternotomy, bypass, عملية قلب مفتوح',
        'Phase I to III rehab following Coronary Artery Bypass Graft.',
        'TENS (Sternal Pain)',
        'Conventional TENS. Freq 100Hz.',
        'Para-sternal region (avoid placing over heart directly/Pacemaker). Parallel to scar.',
        '/static/cabg.jpg',
        'Manage sternotomy pain to allow coughing/breathing.',
        'Contraindicated over Chest',
        'Never use therapeutic US over the heart or pacemaker.',
        'N/A',
        '1. Deep Breathing & Incentive Spirometry.\n2. Sternal Precautions.\n3. Progressive walking program.',
        'Phase 1: 1 week. Phase 2: 3-6 months.',
        'Return to work: 6-12 weeks.',
        'AACVPR Guidelines'
    )
""")

# 18. Renal Failure
cursor.execute("""
    INSERT INTO protocols VALUES (
        NULL,
        'ESRD & Hemodialysis Rehabilitation',
        'kidney failure, dialysis, fatigue, weakness, renal, الغسيل الكلوي',
        'Exercise training for patients undergoing hemodialysis.',
        'NMES (Intradialytic)',
        'Applied to Quads/Calves during dialysis. Freq: 30-50Hz.',
        'Large electrodes on Quadriceps muscle belly and/or Gastrocnemius.',
        '/static/renal.jpg',
        'Prevent muscle wasting in sedentary dialysis patients.',
        'N/A', 'Not standard.', 'N/A',
        '1. Intradialytic Cycling (Bed bike).\n2. Low intensity resistance training.\n3. Energy conservation.',
        'Ongoing (3x/week during sessions).',
        'Improves dialysis efficiency (Kt/V).',
        'K/DOQI Guidelines'
    )
""")

# 19. Lymphedema
cursor.execute("""
    INSERT INTO protocols VALUES (
        NULL,
        'Lymphedema Management',
        'swelling, lymph, mastectomy, arm swelling, edema, التورم الليمفاوي',
        'Chronic accumulation of protein-rich fluid usually after cancer surgery.',
        'Not Primary Treatment',
        'Electrical stimulation is rarely used. Focus is on CDT.',
        'N/A',
        '/static/lymph.jpg',
        'N/A',
        'Contraindicated (Standard Thermal)',
        'Thermal US can increase lymph production. *Low Level Laser* is preferred.',
        'Avoid Thermal Ultrasound.',
        '1. Complex Decongestive Therapy (CDT).\n2. Manual Lymph Drainage (MLD).\n3. Compression Bandaging.\n4. Decongestive Exercises.',
        'Intensive Phase: 2-4 weeks daily.',
        'Condition is manageable but not curable.',
        'International Society of Lymphology'
    )
""")

# 20. Diastasis Recti
cursor.execute("""
    INSERT INTO protocols VALUES (
        NULL,
        'Diastasis Recti (Post-Partum)',
        'abdominal separation, pregnancy, tummy, post natal, انفصال عضلات البطن',
        'Separation of the rectus abdominis muscles during/after pregnancy.',
        'NMES (Adjunct)',
        'Target: Rectus Abdominis. *Caution*.',
        'Bipolar placement on Rectus Abdominis bellies (avoid midline gap).',
        '/static/diastasis.jpg',
        'Assist in recruitment of abdominal wall.',
        'N/A',
        'Real-time Ultrasound Imaging is used for *Biofeedback*.',
        'Diagnosis and Biofeedback.',
        '1. Transverse Abdominis Activation.\n2. Pelvic Floor Kegels.\n3. Heel Slides with core brace.',
        '8-12 weeks.',
        'Surgery considered if gap > 2.5cm persists.',
        'Women''s Health PT Guidelines'
    )
""")

# 21. Labor Pain
cursor.execute("""
    INSERT INTO protocols VALUES (
        NULL,
        'Labor Pain Management',
        'birth, delivery, labor, pain relief, pregnancy, الولادة',
        'Non-pharmacological pain relief during the first stage of labor.',
        'Obstetric TENS',
        'Burst (between contractions), High Freq 100Hz (during contraction).',
        'Paravertebral: T10-L1 (Upper) and S2-S4 (Lower).',
        '/static/labor.jpg',
        'Significant pain reduction via Gate Control Mechanism.',
        'N/A', 'Not indicated.', 'N/A',
        '1. Birthing ball exercises.\n2. Pelvic rocking.\n3. Breathing techniques.',
        'Duration of labor.',
        'Safe for mother and baby.',
        'Cochrane Review on TENS'
    )
""")

# 22. Urinary Incontinence
cursor.execute("""
    INSERT INTO protocols VALUES (
        NULL,
        'Stress Urinary Incontinence',
        'leakage, pelvic floor, bladder, weakness, women health, سلس البول',
        'Involuntary leakage of urine during exertion.',
        'Vaginal/Anal Electrical Stimulation',
        'Freq: 50Hz. Time: 15-20 mins.',
        'Internal Probe (Vaginal or Anal).',
        '/static/pelvic.jpg',
        'Strengthen pelvic floor muscles reflexively.',
        'N/A', 'N/A', 'N/A',
        '1. Kegel Exercises (Fast flicks and Long holds).\n2. The "Knack" maneuver.\n3. Core strengthening.',
        '3-6 months.',
        'Success rate of conservative PT is >70%.',
        'ICS Guidelines'
    )
""")

# 23. Osteoporosis
cursor.execute("""
    INSERT INTO protocols VALUES (
        NULL,
        'Osteoporosis & Fall Prevention',
        'bone density, fragile bones, elderly, fracture risk, هشاشة العظام',
        'Management of reduced bone density in elderly to prevent fractures.',
        'N/A',
        'Modalities used only for associated pain.',
        'N/A (Avoid spinal flexion/manipulation).',
        '/static/osteoporosis.jpg',
        'N/A',
        'Caution', 'Avoid heavy manual pressure.', 'N/A',
        '1. Weight-Bearing Exercises.\n2. Resistance Training.\n3. Balance Training (Tai Chi).\n4. Postural extension.',
        'Lifelong.',
        'Exercise can reduce fracture risk.',
        'NOF Clinician''s Guide'
    )
""")

# 24. Mechanical Low Back Pain (Repeated for safety, standard entry)
cursor.execute("""
    INSERT INTO protocols VALUES (
        NULL,
        'Mechanical Low Back Pain',
        'lbp, back pain, lumbago, strain, stiffness, ألم أسفل الظهر',
        'General non-specific low back pain involving muscles/joints.',
        'TENS / IFC / Heat',
        'IFC: 4000Hz. TENS: 80-100Hz. Heat pack: 20 mins.',
        'Paravertebral muscles (Lumber region). 4 Electrodes (IFC) crossing pain center.',
        '/static/lbp.jpg',
        'Pain modulation to allow movement.',
        'Indicated (Thermal)',
        '1 MHz, Continuous, 1.5 W/cm². Paraspinal muscles.',
        'Relax muscle spasm and increase blood flow.',
        '1. Cat-Camel stretch.\n2. Child''s Pose.\n3. Bridging.\n4. Lumbar rotations.',
        '4-6 weeks.',
        'Encourage early return to activity.',
        'ACP Guidelines for Low Back Pain'
    )
""")

# 25. Plantar Fasciitis (FIXED: Added Placement)
cursor.execute("""
    INSERT INTO protocols VALUES (
        NULL,
        'Plantar Fasciitis',
        'heel pain, foot pain, morning pain, arch pain, شوكة عظمية',
        'Inflammation of the thick band of tissue (plantar fascia) causing heel pain.',
        'Iontophoresis (if available) or TENS',
        'TENS: 100 Hz, Sensory level. Ionto: Dexamethasone, 40 mA-min.',
        'Placement: Medial calcaneal tubercle and arch (or bracket the heel).',
        '/static/plantar.jpg',
        'Short term pain relief.',
        'Indicated (Pulsed or Continuous)',
        '3 MHz, 1.0-1.5 W/cm². Continuous for chronic cases. Time: 5-8 mins.',
        'Improve tissue extensibility before manual therapy or stretching.',
        '1. Plantar Fascia Stretch.\n2. Calf Stretching.\n3. Frozen Water Bottle Roll.\n4. Towel Curls.',
        'Session: 40 mins. Home program essential.',
        'Resolution can take 6-12 months.',
        'JOSPT Clinical Guidelines'
    )
""")

# 26. Carpal Tunnel Syndrome (FIXED: Added Placement)
cursor.execute("""
    INSERT INTO protocols VALUES (
        NULL,
        'Carpal Tunnel Syndrome',
        'wrist pain, hand numbness, tingling fingers, cts, اختناق العصب',
        'Compression of the median nerve as it travels through the carpal tunnel in the wrist.',
        'TENS or Ultrasound',
        'TENS: 100 Hz, Sensory. No motor contraction.',
        'Placement: Over the carpal tunnel (wrist) and proximal forearm.',
        '/static/carpal.jpg',
        'Pain management only.',
        'Indicated (Non-Thermal)',
        'Freq: 3 MHz. Duty Cycle: 20% (Pulsed). Intensity: 0.8 W/cm². Time: 5 mins.',
        'Reduce inflammation within the carpal tunnel.',
        '1. Median Nerve Gliding Exercises.\n2. Tendon Gliding Exercises.\n3. Wrist flexor stretching.',
        'Session: 30 mins. Freq: 2/week.',
        'Conservative management effective in mild-moderate cases.',
        'APT Hand and Upper Extremity Guidelines'
    )
""")

# 27. Patellofemoral Pain Syndrome (PFPS)
cursor.execute("""
    INSERT INTO protocols VALUES (
        NULL,
        'Patellofemoral Pain Syndrome (PFPS)',
        'knee pain, runner knee, anterior knee pain, chondromalacia, صابونة الركبة',
        'Pain around or behind the patella, aggravated by loading activities.',
        'NMES (VMO Strengthening)',
        'Target: Vastus Medialis Oblique (VMO). Freq: 50 Hz. Duty: 10/50.',
        'Placement: VMO Motor point and proximal thigh.',
        '/static/pfps.jpg',
        'Re-education of the VMO muscle to improve patellar tracking.',
        'Not Primary Treatment',
        'Generally not effective for PFPS unless specifically targeting retinaculum tightness.',
        'Adjunct only.',
        '1. VMO Strengthening.\n2. Clamshells.\n3. Hip Abduction.\n4. IT Band Stretching.',
        'Session: 45-60 mins. Focus on Hip/Core.',
        '6-8 weeks of strengthening program required.',
        'International Patellofemoral Research Consensus'
    )
""")

connection.commit()
connection.close()
print("Mega Database Updated: Users Table Added + 27 Diseases FIXED & Preserved! 👤🩺")