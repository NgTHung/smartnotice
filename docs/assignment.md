# Course requirements

The course asks a student team to build and publicly deploy an applied machine learning system with a Vietnamese context. Its report explains the complete path from the problem and collected data to model comparisons, evaluation, and an application people can use.

This summary owns the requirement mapping. The original [course brief](reference/ml-project-3.pdf) and [team proposal](reference/proposal.pdf) remain the source documents. Model names below record the team's proposal, not verified capability claims about those models.

## Match work to deliverables

| Course step | SmartNotice interpretation | Evidence |
|---|---|---|
| Define the problem | Extract academic tasks and determine student applicability | Problem definition and event/audience schema |
| Acquire and prepare data | Public faculty/academic-office notices and voluntarily supplied email | Source manifest, collection method, consent references, annotation protocol |
| Preprocess and explore | Parse MIME/HTML, redact identifiers, preserve evidence, compare email and web | Prepared corpus, quality report, three notebooks |
| Compare at least three models | Compare the proposed extraction and applicability approaches | Training code, configuration, saved runs and checkpoints |
| Evaluate and tune | Use group-safe splits, task metrics, error analysis, and calibration | Held-out predictions, confusion matrices, ablations |
| Build a web application | Accept text, .eml, or URL and show editable evidence-backed tasks | Interface and model API |
| Deploy publicly | Serve a demonstrable cloud application | Public URL and demonstration |

The final submission includes a PDF report, source ZIP, the selected model's weights, presentation slides, and the public web URL. Assessment weights are scientific report/theory 30%, code/model 30%, web application 30%, and creativity 10%.

## Follow the milestones

| Milestone | Required evidence |
|---|---|
| Week 3 | Preliminary proposal of 1-2 pages |
| Week 6 | Collection, preprocessing, and EDA progress report |
| Week 10 | Training/evaluation comparisons and selected model |
| Final presentation | Integrated deployed application, final report, slides, and submission artifacts |

## Apply the proposal

The collection target is 150-250 emails and 200-300 web notices, representing about 1,000-2,000 events. Reserve 40-50 web notices for domain testing. Pilot annotation uses 30-50 documents from each source; at least 20% of the annotated documents receive independent annotation by two people. These are targets, not measured dataset sizes.

The event task covers ACTION with TIME, AUDIENCE, CONDITION, CHANNEL, and DOCUMENT arguments. Time relations distinguish START, DEADLINE, and EVENT_TIME. The applicability task predicts APPLIES, NOT_APPLIES, or UNCLEAR from event text and a synthetic student profile.

The proposed extraction comparisons cover a candidate/relation pipeline using TF-IDF with Logistic Regression and LightGBM, a joint span approach using BamiBERT, and local ViT5 structured generation. Applicability comparisons cover audience rules, LightGBM matching features, and a BamiBERT NLI cross-encoder. Compare rules/features with both human and predicted audiences to measure propagated extraction errors.

The proposal calls for editable predictions with source evidence and confidence, calendar export or integration, a FastAPI model API, and no storage of user content or profiles after an application session. PDF notice input is an optional extension. The [evaluation protocol](evaluation.md) owns the measurement details.
