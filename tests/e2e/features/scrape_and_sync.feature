Feature: Scrape a Cookidoo recipe and sync it to Mealie
  As someone running Cookistash
  I want a scraped Cookidoo recipe to end up correctly in Mealie
  So that I can cook from it without retyping anything

  Background:
    Given a default Cookidoo source is configured
    And a default Mealie source is configured

  Scenario: Scraping a recipe stores it with the parsed Cookidoo content
    When I scrape recipe "r96596"
    Then the recipe is stored with a successful scrape status
    And the recipe name is "Pão pita com falafel"

  Scenario: Sending a scraped recipe to Mealie creates it there
    Given recipe "r96596" has been scraped
    When I send recipe "r96596" to Mealie
    Then the recipe exists in Mealie
    And the Mealie recipe has 27 ingredients
    And the Mealie recipe has 13 instructions

  Scenario: Units and foods split correctly even where Mealie's own parser gets them wrong
    Given recipe "r96596" has been scraped
    When I send recipe "r96596" to Mealie
    Then the Mealie recipe has an ingredient with food "sal" and unit "c. chá de"
    And the Mealie recipe has an ingredient with food "alho" and unit "dentes de"

  Scenario: Nutrition data is carried through to Mealie
    Given recipe "r96596" has been scraped
    When I send recipe "r96596" to Mealie
    Then the Mealie recipe's nutrition "calories" is "337.4"

  Scenario: Re-sending an unchanged recipe skips the Mealie push
    Given recipe "r96596" has been scraped and sent to Mealie once
    When I send recipe "r96596" to Mealie again without any changes
    Then the sync is skipped because the content is unchanged

  Scenario: Re-scraping updates the stored recipe content
    Given recipe "r96596" has been scraped
    When the recipe is scraped again
    Then the recipe's last scraped time is updated
    And a new scrape record exists for the recipe
