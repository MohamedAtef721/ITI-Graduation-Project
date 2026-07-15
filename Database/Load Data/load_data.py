import pandas as pd
import pyodbc

# =====================================================
# SQL SERVER CONNECTION
# =====================================================

conn = pyodbc.connect(
    'DRIVER={ODBC Driver 17 for SQL Server};'
    'SERVER=Mohamed;'
    'DATABASE=SmartInventory;'
    'Trusted_Connection=yes;'
)

cursor = conn.cursor()

# =====================================================
# FILE PATH
# =====================================================

BASE_PATH = r"D:\Power Bi ITI\ITI Graduation Project\archive"

# =====================================================
# HELPER FUNCTIONS
# =====================================================

def read_csv(folder, filename):
    path = fr"{BASE_PATH}\{folder}\{filename}"
    df = pd.read_csv(path, sep=';', low_memory=False)
    print(f"  Read {filename}: {len(df)} rows, columns: {list(df.columns)}")
    return df


DATE_COLUMNS = {
    'AccountOpenedDate',
    'OrderDate',
    'PurchaseOrderDate',
    'ExpectedDeliveryDate',
    'InvoiceDate',
    'TransactionDate',
    'TransactionOccurredWhen',
}

def clean_value(col, val):
    try:
        if pd.isna(val):
            return None
    except Exception:
        pass
    if col in DATE_COLUMNS:
        try:
            return pd.to_datetime(val).strftime('%Y-%m-%d')
        except Exception:
            return None
    return val

def insert_dataframe(df, table_name, columns):
    placeholders = ','.join(['?'] * len(columns))
    cols = ','.join(columns)
    sql = f"INSERT INTO {table_name} ({cols}) VALUES ({placeholders})"

    rows_inserted = 0
    for _, row in df.iterrows():
        values = [clean_value(col, row[col]) for col in columns]
        cursor.execute(sql, values)
        rows_inserted += 1

    conn.commit()
    print(f"  ✔ {table_name}: {rows_inserted} rows inserted\n")

# =====================================================
# 1. COUNTRIES
# =====================================================

print("Loading Countries...")
countries = read_csv('Application', 'Application.Countries.csv')
countries = countries[['CountryID', 'CountryName', 'Continent', 'Region']]
insert_dataframe(countries, 'Countries', ['CountryID', 'CountryName', 'Continent', 'Region'])

# =====================================================
# 2. STATE PROVINCES
# =====================================================

print("Loading StateProvinces...")
states = read_csv('Application', 'Application.StateProvinces.csv')
states = states[['StateProvinceID', 'StateProvinceName', 'CountryID']]
insert_dataframe(states, 'StateProvinces', ['StateProvinceID', 'StateProvinceName', 'CountryID'])

# =====================================================
# 3. CITIES
# =====================================================

print("Loading Cities...")
cities = read_csv('Application', 'Application.Cities.csv')
cities = cities[['CityID', 'CityName', 'StateProvinceID', 'LatestRecordedPopulation']].rename(columns={'LatestRecordedPopulation': 'Population'})
insert_dataframe(cities, 'Cities', ['CityID', 'CityName', 'StateProvinceID', 'Population'])

# =====================================================
# 4. EMPLOYEES
# Source : Application.People (IsEmployee = 1)
# =====================================================

print("Loading Employees...")
people = read_csv('Application', 'Application.People.csv')
employees = people[people['IsEmployee'] == 1][['PersonID', 'FullName', 'IsSalesperson']].rename(columns={'PersonID': 'EmployeeID'})
insert_dataframe(employees, 'Employees', ['EmployeeID', 'FullName', 'IsSalesperson'])

# =====================================================
# 5. LOOKUP TABLES
# =====================================================

print("Loading Lookup Tables...")

lookup_tables = [
    {
        'folder'  : 'Sales',
        'file'    : 'Sales.CustomerCategories.csv',
        'table'   : 'CustomerCategories',
        'columns' : ['CustomerCategoryID', 'CustomerCategoryName'],
        'rename'  : {}
    },
    {
        'folder'  : 'Purchasing',
        'file'    : 'Purchasing.SupplierCategories.csv',
        'table'   : 'SupplierCategories',
        'columns' : ['SupplierCategoryID', 'SupplierCategoryName'],
        'rename'  : {}
    },
    {
        'folder'  : 'Sales',
        'file'    : 'Sales.BuyingGroups.csv',
        'table'   : 'BuyingGroups',
        'columns' : ['BuyingGroupID', 'BuyingGroupName'],
        'rename'  : {}
    },
    {
        'folder'  : 'Warehouse',
        'file'    : 'Warehouse.Colors.csv',
        'table'   : 'Colors',
        'columns' : ['ColorID', 'ColorName'],
        'rename'  : {}
    },
    {
        'folder'  : 'Warehouse',
        'file'    : 'Warehouse.StockGroups.csv',
        'table'   : 'Categories',
        'columns' : ['StockGroupID', 'StockGroupName'],
        'rename'  : {'StockGroupID': 'CategoryID', 'StockGroupName': 'CategoryName'}
    },
    {
        'folder'  : 'Application',
        'file'    : 'Application.PaymentMethods.csv',
        'table'   : 'PaymentMethods',
        'columns' : ['PaymentMethodID', 'PaymentMethodName'],
        'rename'  : {}
    },
    {
        'folder'  : 'Application',
        'file'    : 'Application.DeliveryMethods.csv',
        'table'   : 'DeliveryMethods',
        'columns' : ['DeliveryMethodID', 'DeliveryMethodName'],
        'rename'  : {}
    },
    {
        'folder'  : 'Application',
        'file'    : 'Application.TransactionTypes.csv',
        'table'   : 'TransactionTypes',
        'columns' : ['TransactionTypeID', 'TransactionTypeName'],
        'rename'  : {}
    },
]

for item in lookup_tables:
    print(f"Loading {item['table']}...")
    df = read_csv(item['folder'], item['file'])
    df = df[item['columns']]
    if item['rename']:
        df = df.rename(columns=item['rename'])
        final_cols = list(item['rename'].values())
    else:
        final_cols = item['columns']
    insert_dataframe(df, item['table'], final_cols)

# =====================================================
# 6. CUSTOMERS
# Source : Sales.Customers
# =====================================================

print("Loading Customers...")
customers = read_csv('Sales', 'Sales.Customers.csv')
customers = customers[[
    'CustomerID', 'CustomerName', 'CustomerCategoryID', 'BuyingGroupID',
    'DeliveryCityID', 'DeliveryMethodID', 'PhoneNumber', 'WebsiteURL',
    'CreditLimit', 'AccountOpenedDate'
]].rename(columns={'DeliveryCityID': 'CityID'})
insert_dataframe(customers, 'Customers', [
    'CustomerID', 'CustomerName', 'CustomerCategoryID', 'BuyingGroupID',
    'CityID', 'DeliveryMethodID', 'PhoneNumber', 'WebsiteURL',
    'CreditLimit', 'AccountOpenedDate'
])

# =====================================================
# 7. SUPPLIERS
# Source : Purchasing.Suppliers
# =====================================================

print("Loading Suppliers...")
suppliers = read_csv('Purchasing', 'Purchasing.Suppliers.csv')
suppliers = suppliers[[
    'SupplierID', 'SupplierName', 'SupplierCategoryID',
    'DeliveryCityID', 'DeliveryMethodID', 'PhoneNumber', 'WebsiteURL'
]].rename(columns={'DeliveryCityID': 'CityID'})
insert_dataframe(suppliers, 'Suppliers', [
    'SupplierID', 'SupplierName', 'SupplierCategoryID',
    'CityID', 'DeliveryMethodID', 'PhoneNumber', 'WebsiteURL'
])

# =====================================================
# 8. PRODUCTS
# Source  : Warehouse.StockItems + Warehouse.StockItemStockGroups
# Renamed : QuantityPerOuter → UnitsPerPackage
#           RecommendedRetailPrice → RetailPrice
# =====================================================

print("Loading Products...")
stock_items  = read_csv('Warehouse', 'Warehouse.StockItems.csv')
stock_groups = read_csv('Warehouse', 'Warehouse.StockItemStockGroups.csv')

first_group = (
    stock_groups
    .sort_values('StockGroupID')
    .drop_duplicates(subset='StockItemID', keep='first')
    [['StockItemID', 'StockGroupID']]
)

products = stock_items.merge(first_group, on='StockItemID', how='left')
products = products[[
    'StockItemID', 'StockItemName', 'SupplierID', 'StockGroupID',
    'ColorID', 'Brand', 'UnitPrice', 'TaxRate',
    'QuantityPerOuter', 'RecommendedRetailPrice'
]].rename(columns={
    'StockItemID'           : 'ProductID',
    'StockItemName'         : 'ProductName',
    'StockGroupID'          : 'CategoryID',
    'QuantityPerOuter'      : 'UnitsPerPackage',
    'RecommendedRetailPrice': 'RetailPrice'
})
insert_dataframe(products, 'Products', [
    'ProductID', 'ProductName', 'SupplierID', 'CategoryID',
    'ColorID', 'Brand', 'UnitPrice', 'TaxRate',
    'UnitsPerPackage', 'RetailPrice'
])

# =====================================================
# 9. INVENTORY
# Source  : Warehouse.StockItemHoldings
# Renamed : QuantityOnHand → CurrentStock
# =====================================================

print("Loading Inventory...")
inventory = read_csv('Warehouse', 'Warehouse.StockItemHoldings.csv')
inventory = inventory[[
    'StockItemID', 'QuantityOnHand', 'ReorderLevel', 'TargetStockLevel', 'LastCostPrice'
]].rename(columns={
    'StockItemID'   : 'ProductID',
    'QuantityOnHand': 'CurrentStock'
})
insert_dataframe(inventory, 'Inventory', [
    'ProductID', 'CurrentStock', 'ReorderLevel', 'TargetStockLevel', 'LastCostPrice'
])

# =====================================================
# 10. ORDERS
# Source : Sales.Orders
# =====================================================

print("Loading Orders...")
orders = read_csv('Sales', 'Sales.Orders.csv')
orders = orders[[
    'OrderID', 'CustomerID', 'SalespersonPersonID', 'OrderDate', 'ExpectedDeliveryDate'
]].rename(columns={'SalespersonPersonID': 'EmployeeID'})
insert_dataframe(orders, 'Orders', [
    'OrderID', 'CustomerID', 'EmployeeID', 'OrderDate', 'ExpectedDeliveryDate'
])

# =====================================================
# 11. ORDER DETAILS
# Source  : Sales.OrderLines + Warehouse.StockItemHoldings
# Renamed : ExtendedPrice → LineTotal
#           LineProfit    → ProfitAmount
# =====================================================

print("Loading OrderDetails...")
order_lines = read_csv('Sales', 'Sales.OrderLines.csv')
holdings = read_csv('Warehouse', 'Warehouse.StockItemHoldings.csv')[['StockItemID', 'LastCostPrice']]

order_details = order_lines.merge(holdings, on='StockItemID', how='left')
order_details['LineTotal']    = order_details['Quantity'] * order_details['UnitPrice']
order_details['ProfitAmount'] = (order_details['UnitPrice'] - order_details['LastCostPrice']) * order_details['Quantity']

order_details = order_details[[
    'OrderLineID', 'OrderID', 'StockItemID', 'Quantity',
    'UnitPrice', 'TaxRate', 'LineTotal', 'ProfitAmount'
]].rename(columns={'OrderLineID': 'OrderDetailID', 'StockItemID': 'ProductID'})

insert_dataframe(order_details, 'OrderDetails', [
    'OrderDetailID', 'OrderID', 'ProductID', 'Quantity',
    'UnitPrice', 'TaxRate', 'LineTotal', 'ProfitAmount'
])

# =====================================================
# 12. INVOICES
# Source : Sales.Invoices
# =====================================================

print("Loading Invoices...")
invoices = read_csv('Sales', 'Sales.Invoices.csv')
invoices = invoices[[
    'InvoiceID', 'OrderID', 'CustomerID',
    'SalespersonPersonID', 'DeliveryMethodID', 'InvoiceDate'
]].rename(columns={'SalespersonPersonID': 'EmployeeID'})
insert_dataframe(invoices, 'Invoices', [
    'InvoiceID', 'OrderID', 'CustomerID',
    'EmployeeID', 'DeliveryMethodID', 'InvoiceDate'
])

# =====================================================
# 13. INVOICE DETAILS
# Source  : Sales.InvoiceLines
# Renamed : ExtendedPrice → LineTotal
#           LineProfit    → ProfitAmount
# =====================================================

print("Loading InvoiceDetails...")
invoice_lines = read_csv('Sales', 'Sales.InvoiceLines.csv')
invoice_lines = invoice_lines[[
    'InvoiceLineID', 'InvoiceID', 'StockItemID',
    'Quantity', 'UnitPrice', 'TaxRate', 'ExtendedPrice', 'LineProfit'
]].rename(columns={
    'InvoiceLineID': 'InvoiceDetailID',
    'StockItemID'  : 'ProductID',
    'ExtendedPrice': 'LineTotal',
    'LineProfit'   : 'ProfitAmount'
})
insert_dataframe(invoice_lines, 'InvoiceDetails', [
    'InvoiceDetailID', 'InvoiceID', 'ProductID',
    'Quantity', 'UnitPrice', 'TaxRate', 'LineTotal', 'ProfitAmount'
])

# =====================================================
# 14. PURCHASE ORDERS
# Source  : Purchasing.PurchaseOrders
# Removed : EmployeeID (ContactPersonID not used)
# Renamed : OrderDate → PurchaseOrderDate
# =====================================================

print("Loading PurchaseOrders...")
purchase_orders = read_csv('Purchasing', 'Purchasing.PurchaseOrders.csv')
purchase_orders = purchase_orders[[
    'PurchaseOrderID', 'SupplierID', 'DeliveryMethodID',
    'OrderDate', 'ExpectedDeliveryDate'
]].rename(columns={'OrderDate': 'PurchaseOrderDate'})
insert_dataframe(purchase_orders, 'PurchaseOrders', [
    'PurchaseOrderID', 'SupplierID', 'DeliveryMethodID',
    'PurchaseOrderDate', 'ExpectedDeliveryDate'
])

# =====================================================
# 15. PURCHASE ORDER DETAILS
# Source : Purchasing.PurchaseOrderLines
# =====================================================

print("Loading PurchaseOrderDetails...")
po_lines = read_csv('Purchasing', 'Purchasing.PurchaseOrderLines.csv')
po_lines = po_lines[[
    'PurchaseOrderLineID', 'PurchaseOrderID', 'StockItemID',
    'OrderedOuters', 'ExpectedUnitPricePerOuter'
]].rename(columns={
    'PurchaseOrderLineID'      : 'PurchaseOrderDetailID',
    'StockItemID'              : 'ProductID',
    'OrderedOuters'            : 'QuantityOrdered',
    'ExpectedUnitPricePerOuter': 'UnitCostPrice'
})
insert_dataframe(po_lines, 'PurchaseOrderDetails', [
    'PurchaseOrderDetailID', 'PurchaseOrderID', 'ProductID',
    'QuantityOrdered', 'UnitCostPrice'
])

# =====================================================
# 16. CUSTOMER TRANSACTIONS
# Source  : Sales.CustomerTransactions
# Added   : InvoiceID
# Renamed : AmountExcludingTax → NetAmount
#           OutstandingBalance → RemainingBalance
# =====================================================

print("Loading CustomerTransactions...")
cust_trans = read_csv('Sales', 'Sales.CustomerTransactions.csv')
cust_trans = cust_trans[[
    'CustomerTransactionID', 'CustomerID', 'InvoiceID',
    'TransactionTypeID', 'PaymentMethodID', 'TransactionDate',
    'AmountExcludingTax', 'TaxAmount', 'TransactionAmount', 'OutstandingBalance'
]].rename(columns={
    'AmountExcludingTax': 'NetAmount',
    'OutstandingBalance': 'RemainingBalance'
})
insert_dataframe(cust_trans, 'CustomerTransactions', [
    'CustomerTransactionID', 'CustomerID', 'InvoiceID',
    'TransactionTypeID', 'PaymentMethodID', 'TransactionDate',
    'NetAmount', 'TaxAmount', 'TransactionAmount', 'RemainingBalance'
])
# =====================================================
# 17. SUPPLIER TRANSACTIONS
# Source  : Purchasing.SupplierTransactions
# Added   : PurchaseOrderID
# Renamed : OutstandingBalance → RemainingBalance
# =====================================================

print("Loading SupplierTransactions...")
supp_trans = read_csv('Purchasing', 'Purchasing.SupplierTransactions.csv')

supp_trans = supp_trans[[
    'SupplierTransactionID',
    'SupplierID',
    'PurchaseOrderID',
    'TransactionTypeID',
    'PaymentMethodID',
    'TransactionDate',
    'AmountExcludingTax',
    'TaxAmount',
    'TransactionAmount',
    'OutstandingBalance'
]].rename(columns={
    'AmountExcludingTax': 'NetAmount',
    'OutstandingBalance': 'RemainingBalance'
})

insert_dataframe(supp_trans, 'SupplierTransactions', [
    'SupplierTransactionID',
    'SupplierID',
    'PurchaseOrderID',
    'TransactionTypeID',
    'PaymentMethodID',
    'TransactionDate',
    'NetAmount',
    'TaxAmount',
    'TransactionAmount',
    'RemainingBalance'
])

# =====================================================
# 18. INVENTORY TRANSACTIONS
# Source : Warehouse.StockItemTransactions
# Added  : InvoiceID, PurchaseOrderID
# =====================================================

print("Loading InventoryTransactions...")
inv_trans = read_csv('Warehouse', 'Warehouse.StockItemTransactions.csv')
inv_trans = inv_trans[[
    'StockItemTransactionID', 'StockItemID', 'TransactionTypeID',
    'CustomerID', 'SupplierID', 'InvoiceID', 'PurchaseOrderID',
    'Quantity', 'TransactionOccurredWhen'
]].rename(columns={
    'StockItemTransactionID' : 'TransactionID',
    'StockItemID'            : 'ProductID',
    'TransactionOccurredWhen': 'TransactionDate'
})
insert_dataframe(inv_trans, 'InventoryTransactions', [
    'TransactionID', 'ProductID', 'TransactionTypeID',
    'CustomerID', 'SupplierID', 'InvoiceID', 'PurchaseOrderID',
    'Quantity', 'TransactionDate'
])

# =====================================================
# FINISH
# =====================================================

print("=" * 50)
print("ALL TABLES LOADED SUCCESSFULLY")
print("=" * 50)

cursor.close()
conn.close()