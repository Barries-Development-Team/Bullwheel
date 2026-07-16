## Label Printing Design Requirements

My goal is to create an easy to use framework to add "Print Label" buttons to a variety of views and forms. Ideally, there should be no back-and-forth between client and server during this process. In other words, when a print button is pressed, the client provides the server with all the helpful information it can, and the rest is handled by the server. 

In this context, there are two types of DocTypes: Native and Resolved. Native DocTypes are the DocTypes that existing Zebra Label Templates are designed to work with. Current examples include the DocTypes "Ascend Product" and "Warehouse Location". Resolved DocTypes contain Link fields (or Dynamic Link fields) that link to either a Native DocType, or another Resolved DocType.

### Current Implementation

As of now, only printing of Native Self documents is properly implemented. Printing resolved selection involves back-and-forth between teh client and server.

**Modules**
- UI Add Print Button Function: `bullwheel.printing.add_print_button`
- print_label Server Action: `bullwheel.label_printing.print_labels`

### Button Types

1. Form Button  
   1. Must support printing both “self” and a table/grid selection.  
   2. Added to current “frm”  
   3. **Parameters (bolded arguments must be provided to server action)**  
      1. frm  
      2. label (displayed button label)  
      3. **slot** (label type; swap\_tag, ascend\_tag, etc)  
      4. **doctype**  
      5. **items**  
      6. group  
      7. empty\_message  
2. List View Action  
   1. TBD

### Print Types

1. Native Self (A)  
   1. E.g. Ascend Product, Warehouse location Document view.  
   2. Call print_labels directly since ‘name’ is within scope.  
2. Native Selection (A, B)  
   1. E.g. Ascend Product List View, (possibly) selection of New Products.  
   2. Call print_labels directly since ‘name’ is within scope.  
3. Resolved Self (A)  
   1. E.g. Vendor Product Document View  
   2. Call print_labels wrapper  
4. Resolved Selection (A,B)  
   1. E.g. selected Order Receipt Items, Vendor Product List View  
   2. Call print_labels wrapper

### Implementation Ideas

- Explicitly pass the called server action as an argument for the UI add-button functions.