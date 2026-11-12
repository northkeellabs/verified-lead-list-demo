# Lead-list sample: 20 private secondary schools in Ile-de-France

A small, verified B2B sample of private lycees and colleges in the Paris region (Ile-de-France), built to show the research and verification method. Every row links back to its public source record. Only generic school contacts are included; no named individuals.

## Source

French Ministry of Education open directory (Annuaire de l education, dataset fr-en-annuaire-education), pulled live through the official Opendatasoft API at data.education.gouv.fr. Filter: private establishments (statut_public_prive = Prive), open, with a website listed, in the chosen region and school types.

## Selection

Candidates are sorted by UAI (the official school ID), lycees first, then taken round-robin across the departements so the sample is spread out. Duplicate UAI and duplicate website domains are skipped. The selection is deterministic: rerunning gives the same schools.

## Verification steps

1. Website: HTTP GET, redirects followed, 10 s timeout, browser User-Agent. Status 2xx/3xx is live; the final URL after redirects is recorded.
2. Official email (from the directory): the domain is checked for MX records with nslookup.
3. Website email: the homepage and one contact page (link containing contact) are scanned for addresses (mailto and plain text). Only addresses on the own domain of the school are kept, and only generic mailboxes (contact, secretariat, accueil, direction, etc.). Personal-looking addresses are excluded. Emails are never guessed or constructed; the cell is blank if none is published.
4. Phone: normalised to +33 format.
5. Duplicate check on UAI and on website domain.

## Columns

school_name, school_type: name and type from the directory. uai_id: official school ID. address, postcode, city, departement: location. phone_intl: phone in +33 format. official_email: generic email listed in the directory. official_email_mx_ok: yes/no, whether its domain accepts mail. website: final URL after redirects. website_status: live/down with HTTP status. website_email: generic emails found on the site of the school. contact_page_url: contact page found on the site. source_directory_url: link to the record of the school in the directory. verified_on: date of the checks. notes: contract type (private schools under state contract) and any issue found.

## Rerun

Requires Python 3 with requests (openpyxl optional, for the xlsx). Run python build_leads.py for the default 20 rows. Parameters: --region, --types, --count, --out (for example --count 300 --out my_list). Outputs my_list.csv (UTF-8 with BOM, opens correctly in Excel) and my_list.xlsx.

## Known limits

The directory is only as fresh as the last ministry update. Some school sites block automated requests (HTTP 403) or time out, and are marked down even if they work in a browser. Websites that publish no generic email on their own domain, or only a contact form, have a blank website_email. Some directory emails are institutional academy addresses (ac-versailles.fr, ac-creteil.fr). MX lookups rely on the local DNS resolver.

## Data licence and privacy

Source data: Ministere de l'Education nationale, Annuaire de l'education (data.education.gouv.fr), published under the Licence Ouverte / Open Licence 2.0 (Etalab). The sample CSV and XLSX are derived from it, with website checks added on the date in the verified_on column; they are shared under the same licence. The code is MIT (see LICENSE).

The list holds only organisation-level contacts that the schools or the ministry publish (generic mailboxes, switchboard numbers). No named individuals and no guessed addresses. Anyone using a list like this for outreach is still responsible for GDPR and ePrivacy rules in their country.

## About

Built by Northkeel Labs (https://northkeellabs.com) as a sample of a verified lead-research pipeline: official registries first, every row traceable to its source, checks recorded per row. Independent project, not affiliated with the French Ministry of Education.