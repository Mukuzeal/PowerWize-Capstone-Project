# -*- coding: utf-8 -*-
"""
Content model for the EnergyWize Solutions site.

Everything the site says lives here. build.py turns it into static HTML.
Facts (registration numbers, batch dates, contact details) are transcribed
from EnergyWize's own published material — do not invent additions.
"""

SITE = {
    "legal": "EnergyWize Solutions Inc.",
    "short": "EnergyWize",
    "dba": "E-Wize Solutions",
    "tagline": "Powering a sustainable future",
    "domain": "e-wizesolutions.com",
    "url": "https://e-wizesolutions.com",
    "address_lines": [
        "10F Tower 1, Paseo de Roces",
        "Chino Roces Avenue, Pio del Pilar",
        "City of Makati, Fourth District NCR 1230",
        "Philippines",
    ],
    "emails": [
        ("General enquiries", "energywizesolutions@gmail.com"),
        ("Training registrations", "ewize.trainings@gmail.com"),
    ],
    "phones": [
        "+63 927 515 1817",
        "+63 2 8661 5909",
        "+63 945 873 6547",
        "+63 917 187 9905",
    ],
    "social": [
        ("Facebook", "https://www.facebook.com/", "facebook"),
        ("Instagram", "https://www.instagram.com/", "instagram"),
        ("YouTube", "https://www.youtube.com/", "youtube"),
        ("X", "https://x.com/", "x"),
        ("LinkedIn", "https://www.linkedin.com/", "linkedin"),
    ],
}

# Department of Energy registrations, as printed on the corporate seal.
REGISTRATIONS = [
    ("Certified Energy Manager", "DOE-RTI-CEM-250300115", "Recognized Training Institution"),
    ("Certified Energy Auditor", "DOE-RTI-CEA-250400113", "Recognized Training Institution"),
    ("Government Energy Management Program", "DOE-RTI-GEMP-25041500008", "Recognized Training Institution"),
    ("Recertification — Energy Managers", "DOE-RTI-RCEM-250711511", "Recognized Training Institution"),
    ("Recertification — Energy Auditors", "DOE-RTI-RCEA-250711321", "Recognized Training Institution"),
]

CREDENTIALS = [
    "Registered ESCO",
    "DOE-Recognized Training Institution",
    "RA 11285 compliance",
    "ISO 50001 energy management",
    "ISO 50002 energy audits",
    "Level 1—3 audits",
]

NAV = [
    ("Home", "index.html"),
    ("Capabilities", "capabilities.html"),
    ("Programs", "programs.html"),
    ("Company", "about.html"),
]

# ---------------------------------------------------------------------------
# CAPABILITIES — what EnergyWize sells to organisations
# ---------------------------------------------------------------------------
CAPABILITIES = [
    {
        "slug": "energy-audits",
        "no": "C-01",
        "icon": "audit",
        "title": "Energy Audits",
        "kicker": "Find the waste before you spend on the fix",
        "blurb": "Level 1 walk-through, Level 2 detailed, and Level 3 investment-grade audits, "
                 "conducted by DOE-accredited Certified Energy Auditors against ISO 50002.",
        "specs": ["ISO 50002", "Level 1—3", "M&V", "IGA"],
        "hero_lines": ["Energy", "audits"],
        "lede": "As a DOE-registered Energy Service Company, EnergyWize goes past diagnostics. "
                "An audit that ends at a report has not saved anything — ours end at verified performance.",
        "body": [
            "EnergyWize Solutions Inc. is a Department of Energy–registered Energy Service Company (ESCO). "
            "Our audits are conducted by qualified and experienced Certified Energy Auditors across "
            "commercial, industrial, and institutional facilities.",
            "Our expertise covers Level 1 (walk-through), Level 2 (detailed), and Level 3 (investment-grade) "
            "energy audits, giving organisations an in-depth analysis of consumption patterns and system "
            "performance. Through these audits we identify inefficiencies, energy-saving opportunities, and "
            "cost-reduction measures tailored to each client's operations.",
            "As a recognised ESCO we offer end-to-end delivery — from audit recommendations through the "
            "implementation of energy efficiency projects, performance validation, and ongoing energy "
            "management support. This ensures organisations not only meet regulatory requirements but achieve "
            "measurable savings, improved operational efficiency, and long-term sustainability.",
        ],
        "rows": [
            ("Level 1 — Walk-Through Audit",
             "A preliminary assessment. A physical walk-through identifies obvious saving opportunities, "
             "collects basic consumption data, and produces an overview of the energy systems in place.",
             ["Baseline consumption data", "Systems inventory", "Report of findings and areas for further investigation"]),
            ("Level 2 — Detailed Audit",
             "In-depth analysis including detailed measurement and data collection across systems.",
             ["Measured energy use by system", "Energy conservation measures with costed savings",
              "Detailed reporting and implementation strategies"]),
            ("Level 3 — Investment-Grade Audit",
             "A comprehensive evaluation using advanced data collection, analysis, and specialist "
             "modelling software.",
             ["Financial analysis of proposed projects", "Return on investment calculations",
              "Prioritised ECM list with implementation plan"]),
            ("Customised Recommendations",
             "Based on audit results, our Certified Energy Auditors provide recommendations aligned to your "
             "organisation's goals and budget, so the most effective measures are the ones identified.", []),
            ("Implementation Support",
             "Guidance on carrying out recommended measures, including project management, vendor selection, "
             "and technical advice.", []),
            ("Follow-Up and Monitoring",
             "Post-audit, we establish monitoring protocols to track the effectiveness of implemented "
             "measures and confirm that savings continue.", []),
            ("Regulatory Compliance",
             "Our audits meet energy regulations and standards, helping organisations satisfy legal "
             "requirements while strengthening sustainability practice.", []),
        ],
        "cta": ("Request an energy audit", "contact.html#enquiry"),
    },
    {
        "slug": "energy-management",
        "no": "C-02",
        "icon": "ems",
        "title": "Energy Management Systems",
        "kicker": "Savings that survive the audit report",
        "blurb": "ISO 50001-aligned energy management systems designed, implemented, and monitored by "
                 "Certified Energy Managers — with the KPIs and governance that keep them working.",
        "specs": ["ISO 50001", "KPI framework", "RA 11285", "Capacity building"],
        "hero_lines": ["Energy", "management", "systems"],
        "lede": "An Energy Management System is the difference between a one-off saving and a permanent one. "
                "Ours is built by Certified Energy Managers and handed over to your team, not kept as a "
                "consultancy dependency.",
        "body": [
            "At EnergyWize Solutions, our Energy Management System consultancy is delivered by a team of "
            "Certified Energy Managers (CEMs) who bring extensive expertise to helping organisations "
            "optimise their energy use.",
            "We develop and support Energy Management Systems in line with ISO 50001, integrating "
            "energy-saving technologies and the governance structures that keep performance from drifting "
            "back after the first year.",
        ],
        "rows": [
            ("Expert Assessment",
             "Our CEMs conduct thorough assessments of current energy practices to identify inefficiencies "
             "and areas for improvement, analysing consumption patterns, equipment performance, and "
             "operational practices.", []),
            ("Customised Solutions",
             "Based on the assessment findings we develop tailored energy management strategies aligned "
             "with your organisation's goals and objectives.", []),
            ("Implementation Support",
             "We assist in putting the necessary technologies and processes in place effectively, guiding "
             "your team through best practice and facilitating the changes required.", []),
            ("Monitoring and Evaluation",
             "Continuous monitoring is critical to sustained efficiency. We establish key performance "
             "indicators to track progress and evaluate the effectiveness of implemented strategies, "
             "adjusting as needed.", []),
            ("Training and Capacity Building",
             "Our consultancy includes training sessions for your staff, so the knowledge and skills to "
             "maintain and improve energy management stay inside the organisation.", []),
            ("Regulatory Compliance",
             "We ensure your energy management practices comply with relevant regulations and standards, "
             "including the Energy Efficiency and Conservation Act (RA 11285).", []),
            ("Long-Term Strategy Development",
             "We work with you to develop an energy management strategy that aligns with your "
             "sustainability goals and positions you for future performance.", []),
        ],
        "cta": ("Talk to a Certified Energy Manager", "contact.html#enquiry"),
    },
    {
        "slug": "renewable-energy",
        "no": "C-03",
        "icon": "solar",
        "title": "Solar & Renewable Energy",
        "kicker": "Generate the load you could not design out",
        "blurb": "Supply, design, and installation of solar PV systems, inverters, storage, and balance of "
                 "system — sized against a measured load profile, not a sales target.",
        "specs": ["Solar PV", "Inverters", "Storage", "Monitoring"],
        "hero_lines": ["Solar &", "renewable", "energy"],
        "lede": "We size systems after we have measured the load. That order matters: a correctly audited "
                "building usually needs a smaller array than the one it was about to buy.",
        "body": [
            "EnergyWize Solutions supplies high-quality electrical products for renewable energy, backed by "
            "trusted suppliers and comprehensive installation services, so businesses and individuals can "
            "move to sustainable energy effectively.",
            "Our solar PV work covers system sales, design, and installation, supported by post-installation "
            "monitoring and maintenance.",
        ],
        "rows": [
            ("Solar Panels",
             "High-efficiency solar panels designed for output and durability, suited to residential, "
             "commercial, and industrial applications.", []),
            ("Inverters",
             "Efficient inverters that convert solar energy into usable electricity while maintaining "
             "optimal system performance and reliability.", []),
            ("Batteries",
             "Energy storage that holds excess generation for later use, providing power through peak "
             "demand periods and outages.", []),
            ("Accessories & Balance of System",
             "Mounting systems, wiring, and monitoring tools that support installation and extend the "
             "working life of the system.", []),
            ("Expert Consultation & Installation",
             "Our solar specialists guide selection, installation, and maintenance end to end.", []),
            ("Smart Monitoring",
             "Real-time monitoring and optimisation so performance can be verified rather than assumed.", []),
        ],
        "cta": ("Request a solar PV quotation", "contact.html#enquiry"),
    },
    {
        "slug": "mepf",
        "no": "C-04",
        "icon": "mepf",
        "title": "MEPF Solutions",
        "kicker": "Mechanical, electrical, plumbing & fire protection",
        "blurb": "End-to-end supply and installation of efficient building systems that meet modern "
                 "standards for performance, safety, and consumption.",
        "specs": ["Lighting", "HVAC", "Plumbing", "Fire protection"],
        "hero_lines": ["MEPF", "solutions"],
        "lede": "Mechanical, Electrical, Plumbing and Fire Protection systems decide most of a building's "
                "energy bill before anyone switches a light on. We supply and install the versions that "
                "cost less to run.",
        "body": [
            "We provide end-to-end MEPF solutions designed to deliver energy efficiency, performance, and "
            "safety for every project. Our services include the supply and installation of advanced systems "
            "that meet modern building standards and sustainability goals.",
        ],
        "rows": [
            ("Energy-Efficient Lighting",
             "High-performance lighting using LED technology, occupancy sensors, daylight controls, and "
             "automated energy-saving features — lowering power consumption without compromising brightness "
             "or comfort.", []),
            ("Smart Plumbing Fixtures",
             "Sensor-activated faucets, low-flow fixtures, and intelligent water management systems built "
             "for efficiency and hygiene.", []),
            ("High-Performance HVAC",
             "Energy-efficient heating, ventilation, and air conditioning designed for indoor air quality, "
             "temperature control, and long-term performance.", []),
            ("Fire Protection Systems",
             "Advanced fire detection, suppression, and alarm systems, compliant with national safety codes "
             "and industry best practice.", []),
        ],
        "cta": ("Scope an MEPF package", "contact.html#enquiry"),
    },
    {
        "slug": "technical-training",
        "no": "C-05",
        "icon": "training",
        "title": "Technical Training & Certification",
        "kicker": "The people who keep the savings",
        "blurb": "DOE-recognised certification programs — CEM, CEA, GEMP, and recertification — delivered "
                 "by practising energy professionals.",
        "specs": ["CEM", "CEA", "GEMP", "Recertification"],
        "hero_lines": ["Technical", "training &", "certification"],
        "lede": "EnergyWize is a DOE-Recognized Training Institution. Completing our programs qualifies "
                "participants to apply to the Department of Energy for certification.",
        "body": [
            "EnergyWize Solutions offers specialised training designed to strengthen the skills and "
            "knowledge of professionals in the energy management sector. Our programs are tailored to "
            "individuals and organisations seeking to improve energy efficiency practice and achieve "
            "certification across energy management disciplines.",
        ],
        "rows": [
            ("Expert Instructors",
             "All sessions are led by experienced professionals and certified instructors with substantial "
             "backgrounds in energy management and sustainability.", []),
            ("Interactive Learning",
             "Programs emphasise hands-on work and practical application, so participants can apply what "
             "they learn in real facilities.", []),
            ("Certification Preparation",
             "Each program is structured to prepare participants for certification examinations.", []),
            ("Flexible Delivery",
             "In-person workshops, online courses, and customised in-house training to suit different "
             "schedules and learning preferences.", []),
            ("Continued Support",
             "After training, participants receive ongoing support and resources to help them implement "
             "what they have learned and stay current with industry practice.", []),
        ],
        "cta": ("See the 2026 schedule", "programs.html"),
    },
]

# ---------------------------------------------------------------------------
# PROGRAMS — what EnergyWize sells to individuals
# ---------------------------------------------------------------------------
PROGRAMS = [
    {
        "slug": "program-cem",
        "no": "P-01",
        "code": "CEM",
        "title": "Certified Energy Manager",
        "reg": "DOE-RTI-CEM-250300115",
        "audience": "Energy managers, facilities and plant engineers, sustainability leads",
        "length": "7 days across two blocks",
        "blurb": "Equips professionals with the skills to develop, implement, and manage energy efficiency "
                 "initiatives, covering key industry standards and regulatory frameworks.",
        "lede": "The Certified Energy Manager program equips professionals with the skills to develop, "
                "implement, and manage energy efficiency initiatives. Completion enables participants to "
                "apply to the Department of Energy for certification as a Certified Energy Manager.",
        "topics": [
            ("ISO 50001 — Energy Management System", "Fundamentals, benefits, and implementation strategies."),
            ("ISO 50002 — Energy Audit", "Overview, key steps, and energy-saving opportunities."),
            ("Industry Rules & Regulations", "RA 11285, EPIRA, the Renewable Energy Act, and DOE circulars."),
            ("Monitoring & Audit Tools", "Usage, maintenance, and data interpretation."),
            ("Energy Management Systems", "Development, goal-setting, and implementation."),
            ("Energy Audits", "Planning, conducting assessments, and reporting findings."),
            ("Technical Competencies", "Electrical, mechanical, and lighting system optimisation."),
        ],
        "benefits": [
            "Completion enables participants to apply to the DOE for certification as a Certified Energy Manager.",
            "Earn Certified Energy Manager (CEM) recognition.",
            "Enhance career opportunities in the energy sector.",
            "Develop expertise in energy audits, management, and regulatory compliance.",
        ],
        "schedule_key": "cemcea",
    },
    {
        "slug": "program-cea",
        "no": "P-02",
        "code": "CEA",
        "title": "Certified Energy Auditor",
        "reg": "DOE-RTI-CEA-250400113",
        "audience": "Practising auditors, consulting engineers, ESCO technical staff",
        "length": "7 days across two blocks",
        "blurb": "Builds the expertise to conduct energy audits, identify energy-saving opportunities, and "
                 "ensure compliance with energy efficiency regulations.",
        "lede": "The Certified Energy Auditor program equips professionals with the expertise to conduct "
                "energy audits, identify energy-saving opportunities, and ensure compliance with energy "
                "efficiency regulations. Successful completion enables participants to apply for "
                "certification with the Department of Energy as a Certified Energy Auditor.",
        "topics": [
            ("ISO 50001 — Energy Management System", "Basic awareness."),
            ("ISO 50002 — Energy Audit Standards", "Basic awareness."),
            ("Energy Laws & Regulations", "RA 11285, EPIRA, the Renewable Energy Act, and DOE circulars."),
            ("Operation & Maintenance of Audit Tools", "Power meters, thermal cameras, leak detectors, and related instruments."),
            ("Energy Audit Planning & Execution", "Site inspections, data collection, and reporting."),
            ("Technical Competencies", "Building envelope performance; pump, steam and compressed air optimisation; "
                                        "electrical and mechanical systems; lighting system efficiency."),
        ],
        "benefits": [
            "Completion qualifies participants to apply for DOE certification as a Certified Energy Auditor.",
            "Enhanced career opportunities in energy auditing and management.",
            "Practical knowledge in energy efficiency assessment and implementation.",
            "Compliance expertise in local and international energy regulations.",
        ],
        "schedule_key": "cemcea",
    },
    {
        "slug": "program-gemp",
        "no": "P-03",
        "code": "GEMP",
        "title": "Government Energy Management Program",
        "reg": "DOE-RTI-GEMP-25041500008",
        "audience": "Government agencies, GOCCs, SUCs, LGUs, hospitals, public institutions",
        "length": "3 days · 9:00am — 4:00pm",
        "blurb": "Training and workshop for government employees and officials on regulatory compliance, "
                 "policy development, and efficiency best practice in government operations.",
        "lede": "Under RA 11285, the Government Energy Management Program mandates that all government "
                "agencies — including government-owned and controlled corporations, state universities and "
                "colleges, hospitals, and other public institutions — lead by example in implementing energy "
                "efficiency and conservation initiatives.",
        "topics": [
            ("RA 11285 & GEMP Implementation", "Legal framework, mandates, and compliance."),
            ("Incentives & Financing Options", "Funding mechanisms and support for energy projects."),
            ("GEMP Online System Workshop", "Hands-on training for monitoring and reporting."),
            ("Cost-Benefit Analysis", "Evaluating the financial viability of energy projects."),
            ("EECP Formulation", "Developing and implementing Energy Efficiency & Conservation Programs."),
        ],
        "benefits": [
            "Ensure compliance with RA 11285.",
            "Identify cost-saving energy efficiency measures.",
            "Gain technical expertise in energy management.",
            "Access funding and incentives for energy projects.",
            "Receive hands-on training in efficiency tools and strategies.",
        ],
        "schedule_key": "gemp",
    },
    {
        "slug": "program-rcem",
        "no": "P-04",
        "code": "RCEM",
        "title": "Recertification for Energy Managers",
        "reg": "DOE-RTI-RCEM-250711511",
        "audience": "Accredited Energy Managers renewing DOE certification",
        "length": "2 days",
        "blurb": "A two-day program giving accredited Energy Managers the updates, technical refresh, and "
                 "advanced skills required to maintain DOE certification.",
        "lede": "The Recertification Training for Energy Managers provides accredited Energy Managers with "
                "the latest knowledge, technical updates, and advanced skills required to maintain their "
                "certification with the Department of Energy. This two-day program keeps participants "
                "aligned with current policies, regulatory issuances, and emerging technologies in energy "
                "efficiency and conservation.",
        "topics": [
            ("EEC Act Updates", "Updates on the Energy Efficiency and Conservation Act and related DOE issuances."),
            ("Level 2 Energy Audit", "Introduction to detailed audit methodology."),
            ("Energy Conserving Design for Buildings", "Introduction to conserving design principles."),
            ("Advanced Mechanical Systems", "Current practice in mechanical system efficiency."),
            ("Advanced Electrical Systems", "Current practice in electrical system efficiency."),
            ("Advanced Building Envelope", "Envelope performance and improvement."),
            ("Sustainability, Environmental & Water Systems Design", "Integrated resource management."),
            ("IoT and Data Analytics for Energy Efficiency", "Instrumentation and analysis for continuous improvement."),
        ],
        "benefits": [
            "Update on recent developments in RA 11285 and other DOE regulations.",
            "Enhance technical competencies in energy audits, energy-efficient design, and advanced building systems.",
            "Strengthen capability in sustainable practice, water management, and smart technologies.",
            "Lead organisational compliance, optimise energy performance, and drive sustainability initiatives.",
        ],
        "schedule_key": "rcem",
    },
    {
        "slug": "program-rcea",
        "no": "P-05",
        "code": "RCEA",
        "title": "Recertification of Energy Auditors",
        "reg": "DOE-RTI-RCEA-250711321",
        "audience": "Accredited Energy Auditors renewing DOE certification",
        "length": "2 days",
        "blurb": "An advanced two-day program supporting accredited Energy Auditors in renewing DOE "
                 "certification, with current methodology and project evaluation practice.",
        "lede": "The Recertification Training for Energy Auditors is a two-day advanced program designed to "
                "support accredited Energy Auditors in renewing their certification with the Department of "
                "Energy. It keeps participants current on policies, technical methodologies, and industry "
                "best practice in energy auditing and energy efficiency project evaluation.",
        "topics": [
            ("EEC Act Updates", "Updates on the Energy Efficiency and Conservation Act and related DOE issuances."),
            ("Level 2 Energy Audit", "Applied detailed audit methodology."),
            ("Measurement and Verification (M&V)", "Validating savings from energy efficiency and conservation projects."),
            ("Financial Analysis and Modelling", "Supporting informed decision-making and project financing."),
            ("Investment Grade Audit (IGA)", "Preparing audits to investment-grade standard."),
            ("IoT and Data Analytics", "Emerging tools and technologies in energy auditing."),
            ("Renewable Energy Applications", "Renewable integration within audit scope."),
            ("Transport Energy Efficiency", "Internal combustion engines and electric vehicles."),
        ],
        "benefits": [
            "Updates on RA 11285 and other relevant DOE issuances.",
            "Deeper application of Level 2 audit methodology.",
            "Strengthened Measurement and Verification competency.",
            "Expertise in financial analysis, modelling, and investment grade audits.",
        ],
        "schedule_key": "rcea",
    },
]

# ---------------------------------------------------------------------------
# 2026 SCHEDULE — transcribed from the published batch posters
# ---------------------------------------------------------------------------
SCHEDULES = {
    "cemcea": {
        "label": "CEM & CEA",
        "note": "Certified Energy Manager / Certified Energy Auditor. Two blocks per batch.",
        "rows": [
            ("Batch 6", "January 29, 30, 31", "February 5, 6, 7, 8"),
            ("Batch 7", "March 20, 21, 22", "March 26, 27, 28, 29"),
            ("Batch 8", "May 8, 9, 10", "May 14, 15, 16, 17"),
            ("Batch 9", "June 26, 27, 28", "July 2, 3, 4, 5"),
            ("Batch 10", "August 14, 15, 16", "August 20, 21, 22, 23"),
            ("Batch 11", "October 1, 2, 3, 4", "October 9, 10, 11"),
            ("Batch 12", "November 12, 13, 14, 15", "November 19, 20, 21"),
        ],
        "cols": ("Batch", "Block one", "Block two"),
        "meta_last": False,
    },
    "gemp": {
        "label": "GEMP",
        "note": "Government Energy Management Program. Three days, 9:00am to 4:00pm.",
        "rows": [
            ("Run 1", "January 8, 9, 10", "9:00am — 4:00pm"),
            ("Run 2", "March 5, 6, 7", "9:00am — 4:00pm"),
            ("Run 3", "April 23, 24, 25", "9:00am — 4:00pm"),
            ("Run 4", "June 18, 19, 20", "9:00am — 4:00pm"),
            ("Run 5", "July 23, 24, 25", "9:00am — 4:00pm"),
            ("Run 6", "September 24, 25, 26", "9:00am — 4:00pm"),
            ("Run 7", "November 5, 6, 7", "9:00am — 4:00pm"),
        ],
        "cols": ("Run", "Dates", "Hours"),
    },
    "rcem": {
        "label": "RCEM",
        "note": "Recertification training for Energy Managers. Two days per run.",
        "rows": [
            ("Run 1", "January 23 — 24", "2 days"),
            ("Run 2", "February 27 — 28", "2 days"),
            ("Run 3", "April 17 — 18", "2 days"),
            ("Run 4", "May 29 — 30", "2 days"),
            ("Run 5", "July 17 — 18", "2 days"),
            ("Run 6", "September 18 — 19", "2 days"),
            ("Run 7", "October 30 — 31", "2 days"),
            ("Run 8", "December 11 — 12", "2 days"),
        ],
        "cols": ("Run", "Dates", "Duration"),
    },
    "rcea": {
        "label": "RCEA",
        "note": "Recertification training for Energy Auditors. Two days per run.",
        "rows": [
            ("Run 1", "January 16 — 17", "2 days"),
            ("Run 2", "February 20 — 21", "2 days"),
            ("Run 3", "April 10 — 11", "2 days"),
            ("Run 4", "May 22 — 23", "2 days"),
            ("Run 5", "July 10 — 11", "2 days"),
            ("Run 6", "September 11 — 12", "2 days"),
            ("Run 7", "October 23 — 24", "2 days"),
            ("Run 8", "December 4 — 5", "2 days"),
        ],
        "cols": ("Run", "Dates", "Duration"),
    },
}

# ---------------------------------------------------------------------------
# HOME
# ---------------------------------------------------------------------------
HOME = {
    "hero_lines": ["Measure it.", "Manage it.", "Then make it", "renewable."],
    "hero_underline": 3,   # index of the line that gets the drawn amber rule
    "hero_sub": "EnergyWize Solutions is a Department of Energy–recognised training institution and a "
                "registered Energy Service Company. We audit how buildings and plants actually use power, "
                "build the management systems that hold the savings in place, and certify the professionals "
                "who run them.",
    "mandate_title": ["Republic Act 11285 made", "efficiency a legal duty.", "Most organisations still", "treat it as a line item."],
    "mandate_aside": "The Energy Efficiency and Conservation Act obliges designated establishments to appoint "
                     "an energy manager, run conservation programs, and report annually. Compliance and "
                     "cost reduction are the same project.",
    "mandate_rows": [
        ("01", "Appoint an energy manager",
         "Designated establishments must have a qualified energy manager on record with the Department of Energy. "
         "Our CEM program is the DOE-recognised route to that qualification."),
        ("02", "Run a conservation program",
         "An Energy Efficiency and Conservation Program has to exist, be documented, and be measurable — which "
         "means it starts with an audit, not an intention."),
        ("03", "Report annually",
         "Annual consumption reporting to the DOE is mandatory. A monitored Energy Management System produces "
         "that report as a by-product rather than a fire drill."),
        ("04", "Prove the savings",
         "Measurement and verification separates a claimed saving from a banked one. Our auditors are trained to "
         "the standard that regulators and financiers both accept."),
    ],
    "stats": [
        ("5", "", "DOE registrations", "Recognized Training Institution across CEM, CEA, GEMP, and both recertification tracks."),
        ("3", "", "Audit levels", "Walk-through, detailed, and investment-grade — scoped to the decision you need to make."),
        ("2", "", "ISO standards applied", "ISO 50001 for management systems, ISO 50002 for audits."),
        ("30", "", "Training runs in 2026", "Scheduled batches across all five certification programs."),
    ],
    "doors": [
        {
            "no": "01",
            "hue": "var(--signal)",
            "kicker": "For organisations",
            "title": "Cut the bill, then keep it cut",
            "body": "Audit, management system, renewables, and building services — delivered by one registered "
                    "ESCO so nothing falls between consultants.",
            "list": [
                ("C-01", "Energy audits, Level 1 to investment grade"),
                ("C-02", "ISO 50001 energy management systems"),
                ("C-03", "Solar PV supply, design, and installation"),
                ("C-04", "MEPF supply and installation"),
            ],
            "cta": ("View capabilities", "capabilities.html"),
        },
        {
            "no": "02",
            "hue": "var(--amber)",
            "kicker": "For professionals",
            "title": "Get certified. Stay certified.",
            "body": "DOE-recognised certification and recertification programs, taught by people who audit "
                    "buildings for a living.",
            "list": [
                ("P-01", "Certified Energy Manager (CEM)"),
                ("P-02", "Certified Energy Auditor (CEA)"),
                ("P-03", "Government Energy Management Program"),
                ("P-04", "Recertification — managers and auditors"),
            ],
            "cta": ("View 2026 programs", "programs.html"),
        },
    ],
    "method": [
        ("M-01", "Assess", "A walk-through or detailed audit establishes what the facility actually consumes, "
                           "where, and when — measured, not estimated from bills.", "Audit report"),
        ("M-02", "Model", "Conservation measures are costed and ranked. Investment-grade work adds financial "
                          "modelling and return-on-investment analysis so the business case survives scrutiny.", "Prioritised ECM list"),
        ("M-03", "Implement", "We manage delivery — lighting, HVAC, plumbing, fire protection, controls, and "
                              "solar generation — including vendor selection and technical supervision.", "Installed works"),
        ("M-04", "Verify", "Measurement and verification confirms the savings are real and persistent. KPIs "
                           "and reporting hand over to your own energy manager.", "M&V record"),
    ],
    "commitment": "At EnergyWize Solutions we are dedicated to helping our clients achieve their energy "
                  "efficiency goals while maintaining the highest industry standards and regulatory "
                  "compliance. Following the Energy Efficiency and Conservation Act (RA 11285), our "
                  "experienced team is committed to delivering tailored solutions that not only address the "
                  "unique needs of our clients but also contribute to a more sustainable future.",
    "cta_line": "Start with a number you can trust.",
    "cta_sub": "An audit is the cheapest thing we sell and the only one that tells you whether the rest is "
               "worth buying. Tell us what you operate and we will scope one.",
}

# ---------------------------------------------------------------------------
# ABOUT
# ---------------------------------------------------------------------------
ABOUT = {
    "hero_lines": ["A registered ESCO", "that also teaches"],
    "lede": "EnergyWize Solutions Inc. holds Department of Energy recognition as a training institution and "
            "registration as an Energy Service Company. The two sides feed each other: we teach what we "
            "practise, and we practise what the regulations require.",
    "body": [
        "EnergyWize Solutions Inc. (E-Wize Solutions) is a Department of Energy (DOE)-Recognized Training "
        "Institution (RTI) for Certified Energy Manager (CEM), Certified Energy Auditor (CEA), Authorized "
        "Energy Auditor (AEA), and Government Energy Management Program (GEMP) training courses. We also "
        "provide recertification training for Energy Managers and Energy Auditors to support the renewal of "
        "their accreditation with the DOE.",
        "This official recognition enables EnergyWize to deliver DOE-certified training programs fully "
        "aligned with Republic Act No. 11285, the Energy Efficiency and Conservation (EE&C) Act. As an RTI "
        "we are dedicated to raising the standards of energy management across industries by ensuring that "
        "professionals are equipped with the technical competence, regulatory knowledge, and practical tools "
        "to implement energy efficiency and sustainability initiatives successfully.",
        "Our training curriculum includes comprehensive modules on energy audits, energy management systems "
        "(EnMS), compliance with DOE requirements, and the integration of energy-saving technologies. These "
        "programs build capacity among energy professionals, enabling them to lead projects that reduce "
        "consumption, enhance operational efficiency, and contribute to environmental stewardship.",
        "Beyond training, EnergyWize Solutions Inc. is a DOE-Registered Energy Service Company (ESCO). "
        "Through this accreditation we provide a complete suite of energy services.",
    ],
    "services_list": [
        "Comprehensive energy audits (Level 1, Level 2, and Investment Grade Audits) and compliance consulting",
        "Development and support of Energy Management Systems (EnMS) in line with ISO 50001 standards",
        "Solar PV system sales, design, and installation",
        "Supply of electrical products and energy-efficient technologies",
        "MEPF (Mechanical, Electrical, Plumbing, and Fire Protection) solutions",
    ],
    "closing": [
        "With today's increasing energy demand and pressing environmental challenges, energy efficiency and "
        "conservation are no longer optional but essential. EnergyWize stands as a trusted partner to both "
        "public and private organisations, helping them achieve regulatory compliance, financial savings, "
        "operational improvements, and long-term sustainability goals.",
        "At the core of our mission is a commitment to empower individuals and organisations to optimise "
        "energy performance through certified training, expert technical guidance, and innovative solutions.",
    ],
    "vision": "To be the trusted partner in advancing energy efficiency and renewable energy solutions, "
              "empowering businesses and individuals with expert consultancy, innovative technologies, and "
              "specialised training.",
    "mission": "To drive efficiency and sustainability through comprehensive solutions — consultancy, "
               "audits, training, and MEPF installations — that reduce consumption, enhance operational "
               "efficiency, and contribute to a greener future.",
}

# ---------------------------------------------------------------------------
# CONTACT
# ---------------------------------------------------------------------------
CONTACT = {
    "hero_lines": ["Tell us what", "you operate"],
    "lede": "Audit scoping, solar quotations, MEPF packages, and training registrations all start here. "
            "If you already know which program you want, name the batch and we will hold the slot.",
    "reasons": [
        "Energy audit (Level 1, 2, or investment grade)",
        "Energy management system / ISO 50001",
        "Solar PV quotation",
        "MEPF supply and installation",
        "Training registration — CEM or CEA",
        "Training registration — GEMP",
        "Recertification — RCEM or RCEA",
        "Something else",
    ],
}
