"""Common given names (lower case, ASCII-folded) across many cultures.

Used as evidence for person names: "Amanda Singh" is accepted because "amanda"
is a known given name, even when NER misses it (OCR'd screenshots, tables).
Names that are also ordinary English words (may, will, grace, mark, rose, bill...)
are deliberately left out to avoid false positives.
"""

GIVEN_NAMES = frozenset("""
aaron abby abdul abdullah abel abhishek abigail abraham adam adaeze adebayo adeola aditi aditya adrian adriana
agnieszka ahmed ahmad aiden aiko aisha akash akira akosua alan alana albert alberto aleksandra alessandro alex
alexander alexandra alexei alexis alfred alfredo ali alice alicia alina alison allison alvaro amanda amara amelia
amina amir amit amy ana anastasia anders andre andrea andreas andrei andres andrew andrzej aneta angela angelica
angelo anil anita anjali ankit ann anna anne annette anthony antoine anton antonio anu anuj anya arjun arnav arthur
arturo arvind asha ashish ashley ashok astrid aurora austin ava ayaan ayesha ayodele babatunde barbara bartholomew
beatrice beatrix ben benedict benjamin bernard bernadette bethany bianca bienvenido bilal bjorn blessing boris
bradley brandon brenda brian bridget bridgett brigitte bruno bryan caleb camila camille carla carlos carmen
carol caroline carolyn carsten catherine cecilia cedric celine chandra charles charlotte chen chidi chinedu
chioma chloe chris christian christina christine christopher chukwuma claire clara claudia colette colin connor
craig cristina cynthia dagmar daisuke dalia damian daniel daniela danielle daniyal dariusz darius david dayo
deborah deepak deepika delphine denis dennis derek desmond devansh diana diego dimitri dinesh divisha divya
dmitri dominic donald donna dorothy douglas duncan dylan edward edwin eleanor elena eli elijah elisabeth elizabeth
ella ellen emeka emil emilia emiliano emilio emily emma emmanuel enrique eric erik erika ernest esther ethan
eugene eva evan evelyn fabian fatima fatma federico felix fernando filip fiona florence francesca francesco
francis francisco frank franz fred frederick fumiko gabriel gabriela gareth gary gaurav geoffrey george gerald
gerhardt gianluca gina giorgio giovanni giulia gloria gordon graham grazyna gregor gregory gunnar gustavo haruto
hannah hans harold harriet harsh harry hassan heather hector heidi helen helena henrik henry hiroshi hitesh hugo
hyun ian ibrahim idris ifeoma igor imani imran ines ingrid irina isaac isabel isabella isabelle ishaan ivan
jack jacob jacqueline jakub james jamie jan jane janet janice jasmine jason javier jayesh jean jeffrey jennifer
jeremy jerome jessica jiho jin joanna joao joel johan johannes john jonathan jorge jose josef joseph joshua juan
judith julia julian julie julien jun jyoti kai kamal kaori karan karen karim karin karl karsten kasia katarzyna
kate katherine kathleen kavya kayode kazuki keith kelly kenji kenneth kevin khalid kiran kirsten klaus kofi
kristina krzysztof kumar kwame kyle lakshmi lars laura lauren lawrence leah lena leon leonardo li liam lila linda
lisa liu lorenzo louis louise lucas lucia luciana lucy luis luka lukas madhav madhuri magdalena mahmoud maja
malik manish manoj manuel marc marcel marcin marco marcus margaret margarita marguerite maria mariana marie marina
mario marion marisol marek mariusz marta martin martina mary matteo matthew matthias maurice maxim maya megan
mehmet melisa melissa mia michael michal michel michelle miguel mikael mikhail milan miriam mireille mohamed
mohammed mohan monica muhammad nadia nadine nana naomi naresh natalia natalie natasha nathan nathaniel neha neil
nicholas nicola nicolas nicole niels nikhil nikita nikolai nikolaos nina noah noor nora obinna oksana olga oliver
olivia olusegun omar oscar pablo pamela paolo patricia patrick paul paula pavel pawel pedro peter philip philippe
pierre pooja prakash pranav prasad priya priyanka rachel rafael rahul raj rajesh rajiv ramesh ramon raquel ravi
raymond rebecca renata ricardo richard rita robert roberto rohan rohit roland roman ronald rosalind rosa ruth
ryan sabine sachin sahil samantha samuel sandeep sandra sanjay santiago sara sarah sebastian sergei sergio
shanthi sharon shimane shirin shreya siddharth simon simone sneha sofia solveig sonia sophia sophie srinivas
stefan stefanie stephanie stephen steven sunil sunita susan suzanne sven sylvia takashi tamara tamika tanya
tatiana teresa thabo thomas tiago timothy tobias tomas tomasz tyler uchenna ursula valentina valeria vanessa
varun vera veronica victor victoria vijay vikram vincent vinod viktor vivek vladimir walter wei wendy william
wojciech xavier xin yamini yan yasmin yaw yevgeni yiannis yoko yosef yuki yusuf yvonne zainab zara zoe zuzanna
""".split())
