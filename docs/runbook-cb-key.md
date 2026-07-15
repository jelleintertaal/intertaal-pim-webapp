# Runbook: CB-sleutel vernieuwen

## Wanneer is dit nodig?

De tab **CB opzoeken** toont: *"De CB-sleutel is verlopen of ongeldig"*.

De webapp bevraagt CB Online via een Algolia-zoeksleutel. Die sleutel wordt
verkregen door één keer in te loggen op CB Online (cbonline.boekhuis.nl) en
blijft daarna weken tot maanden geldig — hij werkt vanaf elk IP-adres en kan
door alle gebruikers gedeeld worden. Verloopt hij, dan moet iemand hem
eenmalig lokaal vernieuwen. Dit kan **niet** vanuit Azure (browserlogin + MFA).

## Stappen (5-10 minuten, op een laptop met het project)

1. Open een terminal in de projectmap en draai:

   ```
   python scripts\cb_api_export.py --force-login
   ```

2. Er opent een browservenster op CB Online. **Log in** met het
   CB-dealeraccount (inclusief eventuele tweestapsverificatie).
   Het script detecteert de geslaagde login automatisch en sluit af met
   *"Algolia config opgeslagen"*.

3. De nieuwe sleutel staat nu in `workspace\algolia_config.json`
   (drie velden: `app_id`, `api_key`, `index_name`).
   **De lokale app werkt nu direct weer.**

4. Voor de **Azure-webapp**: neem de drie waarden over in de App Settings
   (Azure Portal → App Service → Configuration):

   | App Setting          | Waarde uit algolia_config.json |
   |----------------------|--------------------------------|
   | `CB_ALGOLIA_APP_ID`  | `app_id`                       |
   | `CB_ALGOLIA_API_KEY` | `api_key`                      |
   | `CB_ALGOLIA_INDEX`   | `index_name`                   |

5. Klik **Save** — de App Service herstart automatisch en de CB-tab werkt weer.

## Veiligheidsregels

- De sleutel is een **alleen-lezen zoeksleutel**, maar behandel hem als een
  wachtwoord: niet mailen, niet in chats plakken, alleen in App Settings
  en `workspace\algolia_config.json` (die map gaat nooit mee in de deploy-zip).
- Deel nooit het CB-dealerwachtwoord zelf; alleen de persoon die het runbook
  uitvoert heeft dat nodig, in de browser van CB zelf.

## Achtergrond (voor de beheerder)

- Het browserprofiel met de CB-sessie staat lokaal in
  `..\.playwright-cb-profile`. Zolang die sessie geldig is, kan het script de
  sleutel zelfs **zonder handmatige login** verversen (gewoon zonder
  `--force-login` draaien — het probeert eerst headless).
- Toekomstige verbetering: CB levert ook officiële ONIX-databestanden in
  Azure Blob (container `datacb`). Daarmee kan de CB-lookup op termijn
  volledig zonder sleutel-verversing (en inclusief druk + beschrijving).
