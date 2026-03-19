# **LOGIC MODULE**
The logic module provides a set of functions to handle the logic of the shapes.
It is mostly used to handle the way the shapes are connected to each other.
The [shape](#shape) element is a simple string that according to some rules can be identified as Primary, Inbetween, Combo or Combo Inbetween.

## **Network**
The Network module provides a set of function to handle the shapes network.
The Network is mostly string based, meaning that the shapes are identified by their names.
It also has the ability to handle the association of one of more split maps to a shape.
The Network will check the validity of the shapes before they are added to the network.
A combo shape will not be added if any of the primary shapes are not already present in the network.
The same thing goes for inbetween shapes, if there is no parent shape the inbetween will not be added.
<br>_**Example:** **Network.add_shape("eyeClose50_lidTightner")** will check if "eyeClose" and "lidTightner" are already in the network before adding it.
<br> **Network.add_shape(eyeClose50)** will check if "eyeClose" is in the network before adding it._



## **Shape**
The sahpe element is a string with a set of rules to identify the type of shape it is.
The availble types are:
- **Primary:**<br> A primary shape is a simple string with no special characters.
<br> _**Example:** "eyeClose"_
- **Inbetween:**<br> An inbetwees is a string ending with a 2 digit number. 
<br> _**Example:** "eyeClose50"_.
- **Combo:**<br> A combo is a string with a **SEPARATOR** in it
<br> _**Example:** "eyeClose_lidTightner"._
- **Combo Inbetween:**<br> A combo inbetween is a string with a **SEPARATOR** in it and ending with a 2 digit number.
<br> _**Example:** "eyeClose50_lidTightner"_

