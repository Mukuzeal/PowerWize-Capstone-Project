# -*- coding: utf-8 -*-
"""
Content model for the public EnergyWize site.

Everything the marketing pages say lives here; site_bp.py renders it. Batch
dates are NOT in this file — they come from the `batches` table via
db.get_public_schedule(), so the published calendar and the registration form
dropdowns are always the same data.

Facts (registration numbers, contact details) are transcribed from EnergyWize's
own published material — do not invent additions.
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

# (label, Flask endpoint) — the nav is rendered with url_for.
NAV = [
    ("Home", "registration.index"),
    ("Capabilities", "site.capabilities"),
    ("Programs", "registration.programs"),
    ("Company", "site.about"),
    ("Contact", "site.contact"),
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
        "batch_type": "training",
        "forms": [("Register for CEM", "registration.training")],
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
        "batch_type": "training",
        "forms": [("Register for CEA", "registration.cea_training")],
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
        "batch_type": "gemp_training",
        "forms": [("LGU registration", "registration.gemp_lgu"),
                  ("Other government entities", "registration.gemp_oge")],
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
        "batch_type": "renewal",
        "forms": [("Renew CEM credential", "registration.renewal_cem")],
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
        "batch_type": "renewal",
        "forms": [("Renew CEA credential", "registration.renewal")],
    },
]

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
            "icon": "ems",
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
            "icon": "training",
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
              "specialized training. We envision a sustainable future where smart energy management drives "
              "economic growth, environmental responsibility, and long-term resilience—ensuring that every "
              "watt counts for a better tomorrow.",
    "mission": "At EnergyWize Solutions Inc., doing business as E-Wize Solutions, we are dedicated to driving "
               "energy efficiency, sustainability, and innovation through comprehensive energy solutions. We "
               "provide expert energy management consultancy, energy audits, and technical training, equipping "
               "organizations and individuals with the knowledge and strategies to optimize energy use. Our "
               "services also include the sales and installation of renewable energy systems, solar products, "
               "and Mechanical, Electrical, Plumbing, and Fire Protection (MEPF) solutions, ensuring seamless "
               "integration of cutting-edge technologies for maximum efficiency and reliability. Committed to "
               "environmental stewardship and energy conservation, we strive to be a trusted partner in "
               "transforming energy practices, reducing carbon footprints, and building a cleaner, more "
               "energy-efficient future.",
    "commitment": "At EnergyWize Solutions, we are dedicated to helping our clients achieve their energy "
                  "efficiency goals while maintaining the highest industry standards and regulatory compliance, "
                  "including The Energy Efficiency and Conservation Act (RA 11285). Our experienced team is "
                  "committed to delivering tailored solutions that not only address the unique needs of our "
                  "clients but also contribute to a more sustainable future.",
    "core_values": "At EnergyWize Solutions Inc., we are committed to integrity, innovation, and sustainability in "
                   "delivering energy solutions. We empower businesses and individuals with efficient, compliant, and "
                   "future-ready energy management practices, driving lasting impact for a greener and more resilient "
                   "future.",
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

# ---------------------------------------------------------------------------
# LEGAL — Privacy Policy, Legal Notice, Terms & Conditions.
# Mirrored verbatim from e-wizesolutions.com so the content lives on-site
# instead of linking out. Each section is {"heading": ..., "paragraphs": [...],
# "list": [...] (optional)} rendered in order by site/legal.html.
# ---------------------------------------------------------------------------
PRIVACY_POLICY = {
    "title": "Privacy Policy",
    "effective_date": "February 22, 2025",
    "sections": [
        {"heading": "1. Introduction", "paragraphs": [
            "Welcome to EnergyWize Solutions Inc. (\"Company\", \"we\", \"our\", \"us\"). We are committed to "
            "protecting your personal information and your right to privacy. This privacy policy explains how "
            "we collect, use, disclose, and safeguard your information when you visit our website, use our "
            "services, or otherwise interact with us. If you have any questions or concerns about our policy "
            "or our practices with regard to your personal information, please contact us at "
            "energywizesolutions@gmail.com.",
        ]},
        {"heading": "2. Information We Collect", "paragraphs": [
            "We collect personal information that you voluntarily provide to us when you register on our "
            "website, express an interest in obtaining information about us or our products and services, "
            "participate in activities on our website, or otherwise contact us.",
            "The personal information that we collect depends on the context of your interactions with us and "
            "the website, the choices you make, and the products and features you use. The personal "
            "information we collect may include the following:",
        ], "list": [
            "Personal Information Provided by You: Names, phone numbers, email addresses, mailing addresses, "
            "job titles, and other similar information.",
            "Payment Data: Data necessary to process payments if you make purchases, such as your payment "
            "instrument number (e.g., credit card number) and the security code associated with your payment "
            "instrument.",
            "Log and Usage Data: IP addresses, browser types, operating systems, and access times to improve "
            "our website and services.",
        ]},
        {"heading": "3. Legal Basis for Processing Personal Data", "paragraphs": [
            "We process your personal data based on one or more of the following legal grounds:",
        ], "list": [
            "Legitimate Business Interest: When processing is necessary for our business operations, such as "
            "improving services, preventing fraud, or marketing.",
            "Contractual Necessity: When processing is required to fulfill a contract with you.",
            "Legal Compliance: When required by law to retain or disclose information.",
            "Consent: When you provide explicit consent for specific data uses.",
        ]},
        {"heading": "4. How We Use Your Information", "paragraphs": [
            "We use personal information collected via our website for a variety of business purposes described "
            "below. We process your personal information for these purposes based on our legitimate business "
            "interests, contractual obligations, legal requirements, and/or your consent:",
        ], "list": [
            "To send administrative information to you: This includes product, service, and feature updates, "
            "as well as changes to our terms, conditions, and policies.",
            "To protect our services: Ensuring the security of our website and preventing fraudulent activities.",
            "To enforce our terms, conditions, and policies: Compliance with legal and regulatory requirements.",
            "To respond to legal requests and prevent harm: In case of subpoenas or legal requests, we may need "
            "to inspect our data.",
            "To fulfill and manage orders: Processing purchases, payments, returns, and exchanges.",
            "To administer prize draws and competitions: If you participate in promotional events.",
            "To deliver and facilitate the delivery of services: Ensuring that requested services are provided "
            "efficiently.",
            "To respond to user inquiries and offer support: Addressing your concerns and troubleshooting issues.",
        ]},
        {"heading": "5. Will Your Information Be Shared with Anyone?", "paragraphs": [
            "We only share information with your consent, to comply with laws, to provide you with services, "
            "to protect your rights, or to fulfill business obligations. Specifically, we may need to share "
            "your data with:",
        ], "list": [
            "Service Providers: Third-party vendors, service providers, contractors, or agents who assist in "
            "service delivery.",
            "Business Transfers: In case of a merger, sale, or acquisition of our company.",
            "Legal Obligations: If required to comply with laws, court orders, or governmental requests.",
            "International Data Transfers: If data is transferred outside the Philippines, we ensure that "
            "necessary safeguards are in place to protect your privacy.",
        ]},
        {"heading": "6. Data Retention Policy", "paragraphs": [
            "We retain personal information for as long as necessary to fulfill the purposes outlined in this "
            "policy unless a longer retention period is required by law. Specifically:",
        ], "list": [
            "Customer information related to transactions is retained for at least five (5) years as required "
            "by financial regulations.",
            "Data collected for marketing purposes is retained until you opt out or withdraw consent.",
        ]},
        {"heading": "7. How Do We Keep Your Information Safe?", "paragraphs": [
            "We have implemented appropriate technical and organizational security measures to protect your "
            "personal information. These measures include encryption, secure servers, and access controls. "
            "However, no method of transmission over the Internet or electronic storage is 100% secure, and we "
            "cannot guarantee absolute security.",
        ]},
        {"heading": "8. Breach Notification", "paragraphs": [
            "In case of a data breach that may affect your personal information, we will notify you and "
            "relevant authorities as required by the Data Privacy Act of 2012. We will take immediate action "
            "to mitigate risks and secure affected data.",
        ]},
        {"heading": "9. Third-Party Links", "paragraphs": [
            "Our website may contain links to third-party websites. We are not responsible for the privacy "
            "policies or practices of these external sites. We encourage you to review their policies before "
            "providing any personal data.",
        ]},
        {"heading": "10. Do We Collect Information from Minors?", "paragraphs": [
            "We do not knowingly collect or solicit data from children under 18 years of age. If we become "
            "aware of such data collection, we will take steps to delete it promptly.",
        ]},
        {"heading": "11. Your Privacy Rights", "paragraphs": [
            "Under the Data Privacy Act of 2012, you have the right to:",
        ], "list": [
            "Access your personal data.",
            "Request correction or deletion of your data.",
            "Object to or restrict data processing.",
            "Withdraw consent at any time.",
            "Data portability (request your data in a commonly used format).",
            "File a complaint with the National Privacy Commission (NPC) if your data privacy rights are "
            "violated.",
        ], "closing": [
            "To exercise your rights, please contact us at energywizesolutions@gmail.com.",
        ]},
        {"heading": "12. Cookies and Tracking Technologies", "paragraphs": [
            "Our website may use cookies and similar tracking technologies to enhance user experience. Users "
            "can manage cookie preferences through their browser settings.",
        ]},
        {"heading": "13. Controls for Do-Not-Track Features", "paragraphs": [
            "Our website currently does not respond to \"Do-Not-Track\" (DNT) signals from web browsers. If "
            "such a standard is adopted in the future, we will update our privacy policy accordingly.",
        ]},
        {"heading": "14. Updates to This Policy", "paragraphs": [
            "We may update this privacy policy from time to time. Changes will be posted on our website, and "
            "we encourage you to review the policy periodically.",
        ]},
        {"heading": "15. Contact Us", "paragraphs": [
            "If you have questions or comments about this policy, you may contact us:",
            "EnergyWize Solutions Inc.\n"
            "10F Tower 1 Paseo De Roces, Chino Roces Ave., Pio del Pilar, City of Makati, Metro Manila 1230\n"
            "Phone: 0927 5151817 | +632 8661 5909\n"
            "Email: energywizesolutions@gmail.com",
        ]},
    ],
}

LEGAL_NOTICE = {
    "title": "Legal Notice",
    "effective_date": "March 1, 2025",
    "sections": [
        {"heading": "Introduction", "paragraphs": [
            "Welcome to the EnergyWize Solutions Inc. website. This legal notice applies to the entire contents "
            "of this website under the domain name www.e-wizesolutions.com and to any correspondence by e-mail "
            "between us and you. Please read these terms carefully before using this website.",
        ]},
        {"heading": "Website Operator", "paragraphs": [
            "This website is operated by EnergyWize Solutions Inc., located at 10F Tower 1 Paseo De Roces, "
            "Chino Roces Ave., Pio Del Pilar, City of Makati, Metro Manila 1230, registered in the Philippines.",
        ]},
        {"heading": "Intellectual Property Rights", "paragraphs": [
            "All content on this website, including but not limited to text, graphics, logos, icons, images, "
            "audio clips, digital downloads, data compilations, and software, is the property of EnergyWize "
            "Solutions Inc. or its content suppliers and is protected by international copyright laws. "
            "Unauthorized use, reproduction, or distribution of any content is prohibited.",
        ]},
        {"heading": "Use of Website", "paragraphs": [
            "You are permitted to use our website for your own purposes and to print and download material "
            "from this website, provided that you do not modify any content without our consent. Material on "
            "this website must not be republished online or offline without our permission.",
        ]},
        {"heading": "Visitor Conduct", "paragraphs": [
            "With the exception of personally identifiable information, the use of which is covered under our "
            "Privacy Policy, any material you send or post to this website shall be considered non-proprietary "
            "and not confidential. We shall be free to copy, disclose, distribute, incorporate, and otherwise "
            "use such material for any and all purposes.",
            "When using this website, you shall not post or send to or from this website any material:",
        ], "list": [
            "For which you have not obtained all necessary consents;",
            "That is discriminatory, obscene, pornographic, defamatory, liable to incite racial hatred, in "
            "breach of confidentiality or privacy, which may cause annoyance or inconvenience to others, which "
            "encourages or constitutes conduct that would be deemed a criminal offense, give rise to a civil "
            "liability, or otherwise be contrary to the law in the Philippines;",
            "Which is harmful in nature, including but not limited to, computer viruses, Trojan horses, "
            "corrupted data, or other potentially harmful software or data.",
        ]},
        {"heading": "Links to and from Other Websites", "paragraphs": [
            "This website may contain links to third-party websites. These links are provided for convenience "
            "only, and we do not endorse or assume responsibility for the content or privacy practices of any "
            "third-party sites.",
        ]},
        {"heading": "Disclaimer", "paragraphs": [
            "We take all reasonable steps to ensure that the information on this website is correct and strive "
            "to review and update content periodically to maintain accuracy. However, we do not guarantee the "
            "correctness or completeness of the material on this website. We may make changes to the material "
            "on this website at any time and without notice. The material on this website may be out of date "
            "or, on rare occasions, incorrect, and we make no commitment to ensure that such material is "
            "correct or up to date.",
            "The material on this website is provided without any conditions or warranties of any kind. To the "
            "maximum extent permitted by law, we provide access and use of this website on the basis that we "
            "exclude all representations, warranties, and conditions that might otherwise apply.",
        ]},
        {"heading": "Limitation of Liability", "paragraphs": [
            "To the fullest extent permitted by law, EnergyWize Solutions Inc. shall not be liable for any "
            "direct, indirect, incidental, consequential, or punitive damages arising from your use of this "
            "Website or any linked sites. This exclusion shall include servicing or repair costs and, without "
            "limitation, any other direct, indirect, or consequential loss.",
        ]},
        {"heading": "Governing Law & Jurisdiction", "paragraphs": [
            "This Legal Notice and any disputes related to this Website shall be governed by and interpreted "
            "under the laws of the Philippines. Any legal actions must be brought in the courts of the "
            "Philippines.",
        ]},
        {"heading": "Changes to this Legal Notice", "paragraphs": [
            "We reserve the right to update this Legal Notice at any time. Any changes will be posted on this "
            "page, and your continued use of the Website constitutes acceptance of the updated terms.",
        ]},
        {"heading": "Contact Information", "paragraphs": [
            "For any questions or concerns regarding this Legal Notice, please contact us at:",
            "EnergyWize Solutions Inc.\n"
            "Address: 10F Tower 1 Paseo De Roces, Chino Roces Ave., Pio Del Pilar, City of Makati, Metro "
            "Manila 1230\n"
            "Email: energywizesolutions@gmail.com\n"
            "Phone: 0927 5151817 | +632-86615909",
            "By using this Website, you agree to abide by the terms outlined in this Legal Notice. Continued "
            "use of the Website after any updates or modifications constitutes your acceptance of the revised "
            "terms.",
        ]},
    ],
}

TERMS_CONDITIONS = {
    "title": "Terms and Conditions for Training Courses",
    "effective_date": "April 14, 2025",
    "version": "Version 1.0",
    "sections": [
        {"heading": "1. Applicability", "paragraphs": [
            "1.1 These Terms and Conditions apply to the provision of Certified Energy Manager (CEM), "
            "Certified Energy Auditor (CEA), and Government Energy Management Program (GEMP) training courses "
            "by EnergyWize Solutions, Inc. (\"E-Wize Solutions\") to individuals and organizations.",
        ]},
        {"heading": "2. Definitions", "list": [
            "Customer – the individual or entity registering for the training.",
            "Participant – a person attending the training course.",
            "Training – includes CEM, CEA, and GEMP courses, delivered either online or in person.",
            "Training Materials – printed or digital resources provided during the training.",
        ]},
        {"heading": "3. Registration and Agreement", "paragraphs": [
            "3.1 Completion of registration online or via email, and clicking the \"Register Now\" button or "
            "downloading this document, constitutes agreement to these Terms and Conditions.",
            "3.2 These Terms shall be binding from the moment of registration.",
        ]},
        {"heading": "4. Training Provision", "paragraphs": [
            "4.1 E-Wize Solutions will deliver training as per advertised schedules and content, subject to "
            "change without prior notice.",
            "4.2 In the event of emergencies or unforeseen circumstances (e.g., natural calamities or "
            "unavailability of a trainer), E-Wize reserves the right to reschedule or cancel the training.",
            "4.3 Customers will be notified via email, SMS, or phone.",
        ]},
        {"heading": "5. Customer Responsibilities", "paragraphs": [
            "5.1 Customers must:",
        ], "list": [
            "Cooperate fully during the training.",
            "Provide complete and accurate information during registration.",
        ]},
        {"heading": "6. Payment Terms", "paragraphs": [
            "6.1 Training fees are charged per participant or per group/company and are exclusive of VAT.",
            "6.2 Payments must be made within seven (7) calendar days from invoice issuance and before the "
            "start of the training.",
            "6.3 Non-payment may result in:",
        ], "list": [
            "Loss of training slot,",
            "Suspension of access,",
            "Withholding of certificates.",
        ], "closing": [
            "6.4 Payments must be made in full with no deductions, unless required by law.",
        ]},
        {"heading": "7. Cancellation and Rescheduling", "paragraphs": [
            "7.1 Requests to reschedule training less than ten (10) days prior will incur a 15% rescheduling "
            "fee.",
            "7.2 Non-classroom-based training is non-refundable and cannot be rescheduled.",
            "7.3 Failure to attend the training without notice will not entitle the participant to a refund, "
            "but rejoining on the next available date is allowed without extra charge.",
            "7.4 E-Wize Solutions may cancel or reschedule training. Affected participants will be informed "
            "and offered an alternative schedule.",
            "7.5 Refunds, when applicable, will be processed through the original mode of payment.",
            "7.6 In cases of force majeure, refund or rescheduling will be considered on a case-by-case basis.",
        ]},
        {"heading": "8. Intellectual Property Rights", "paragraphs": [
            "8.1 All intellectual property rights related to training materials remain with E-Wize Solutions.",
            "8.2 Materials may not be copied, scanned, or distributed without written permission.",
            "8.3 Participants may use the materials for internal reference only. Commercial use is prohibited.",
        ]},
        {"heading": "9. Data Privacy and Confidentiality", "paragraphs": [
            "9.1 Customer data will be used solely for training purposes and will be stored securely in "
            "accordance with the Data Privacy Act of 2012.",
            "9.2 Data will not be shared with third parties except as required by law.",
            "9.3 Confidential information shared during training must not be disclosed to others.",
            "9.4 Customers may request access, correction, or deletion of their data by contacting: "
            "energywizesolutions@gmail.com",
        ]},
        {"heading": "10. Termination", "paragraphs": [
            "10.1 E-Wize Solutions may terminate a registration if payments are not received on time.",
            "10.2 Unpaid materials or documents must be returned or withheld as applicable.",
        ]},
        {"heading": "11. Force Majeure", "paragraphs": [
            "E-Wize Solutions shall not be liable for non-performance caused by events beyond its control, "
            "including but not limited to acts of God, government actions, pandemic disruptions, or technical "
            "failures.",
        ]},
        {"heading": "12. Agreement Acknowledgment", "paragraphs": [
            "By registering for or participating in the training, I confirm that I have read, understood, and "
            "agreed to be bound by the Terms and Conditions of EnergyWize Solutions, Inc., including its Data "
            "Privacy Policy.",
        ]},
    ],
}
