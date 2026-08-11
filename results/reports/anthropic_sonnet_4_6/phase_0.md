
# Phase 0 - Manual Check

## Goal
Once the project is setup (data downloaded and config setup successfully), the goal is understand the complexity we are dealing with using the following process:
- Select a database from hf_xlangai_spider/validation_spider.xlsx
- Read few query (natural language) listed there and try to write the script that can solve that question
- Compare the result with gold script (the real answer) and understand what is a real challenge you faced

## Process
- **Database Selected**: Battle_death.sqlite #spider/database/battle_dealth/battle_death.sqlite
- Open the database in DBeaver community
- Write the queries manually (understand the pain AI will solve, only then you can actually gain the buyin of doing this project)

## Queries Run

### Question 1: How many ships ended up being 'Captured'?
**Manual Query**: select count(*) as captured_ship_count from ship where disposition_of_ship = 'Captured';  
**Golden Query**: SELECT count(*) FROM ship WHERE disposition_of_ship  =  'Captured'  
**Status**: Pass  

### Question 2: What is maximum and minimum death toll caused each time?
**Manual Query**: select min(killed) as minimum_killed, max(killed) as maximum_killed from death;  
**Golden Query**: SELECT max(killed) ,  min(killed) FROM death  
**status**: Pass  

### Query 3: What are the ids and names of the battles that led to more than 10 people killed in total.
**Manual Query**: select battle_id, battle_name, num_deaths from (select T1.id as battle_id, T1.name as battle_name, sum(T3.killed) as num_deaths  FROM battle as T1 inner join ship as T2 on T1.id = T2.lost_in_battle  inner join death as T3 on T3.caused_by_ship_id = T2.id group by T1.id) where num_deaths > 10 order by battle_id;  
**Golden Query**: SELECT T1.id ,  T1.name FROM battle AS T1 JOIN ship AS T2 ON T1.id  =  T2.lost_in_battle JOIN death AS T3 ON T2.id  =  T3.caused_by_ship_id GROUP BY T1.id HAVING sum(T3.killed)  >  10  
**Status**: Pass


### Query 4: List the name and date the battle that has lost the ship named 'Lettice' and the ship named 'HMS Atalanta'
**Manual Query**: select T1.name, T1.date from battle T1 inner join ship T2 where T2.name in ('Lettice', 'HMS Atalanta');  
**Golden Query**: SELECT T1.name ,  T1.date FROM battle AS T1 JOIN ship AS T2 ON T1.id  =  T2.lost_in_battle 
WHERE T2.name  =  'Lettice' 
INTERSECT 
SELECT T1.name ,  T1.date FROM battle AS T1 JOIN ship AS T2 ON T1.id  =  T2.lost_in_battle 
WHERE T2.name  =  'HMS Atalanta'  
**status**: Failed  
**Reason**: forget to use 'ON' intersection -> manual mistake  

### Query 5: What are the notes of the death events which has substring 'East'?  
**Manual Query**: select note from death where note like '%EAST%';  
**Golden Query**: select note from death where note like '%EAST%';  
**Status**: Pass
